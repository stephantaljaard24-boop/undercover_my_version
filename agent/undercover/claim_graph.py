"""The claim graph: one claim, from the first look to the payment."""

from typing import Annotated, Any, Literal, TypedDict, cast

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, SystemMessage
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.graph.state import CompiledStateGraph
from langgraph.prebuilt import ToolNode
from langgraph.types import interrupt
from pydantic import BaseModel, Field

from agent.harness.graphs import count_call, retry_policy
from agent.undercover.backend import Backend
from agent.undercover.tools import claim_tools


class ClaimState(TypedDict):
    """What the graph keeps for one claim. The checkpointer saves it after each step."""

    messages: Annotated[list[AnyMessage], add_messages]
    claim_id: str
    decision: str
    payout: str
    explanation: str
    policy_section: str
    needs_sign_off: bool
    model_calls: int


class ClaimDecision(BaseModel):
    """A claims handler's decision on one claim."""

    explanation: str = Field(
        description="2-3 sentences to explain the decision in plain business English"
    )
    policy_section: str = Field(
        description='The section of the policy it relies on, such as "3. Trip Delay"'
    )
    decision: Literal["approve", "decline", "refer"]
    payout: str = Field(
        pattern=r"^\d+(\.\d{1,2})?$",
        description='The amount to pay in US dollars, such as "420.00", or "0.00" for '
        "a decline or a referral",
    )


def initial_input(claim_id: str) -> dict[str, Any]:
    """The state a claim's thread starts with."""
    return {
        "messages": [HumanMessage(f"Decide claim {claim_id}.")],
        "claim_id": claim_id,
        "model_calls": 0,
    }


def after_agent(state: ClaimState) -> Literal["tools", "decide"]:
    """Run the tools the model asked for, or move on to the decision."""
    last = state["messages"][-1]
    return "tools" if isinstance(last, AIMessage) and last.tool_calls else "decide"


def after_record(state: ClaimState) -> str:
    """Pay an approval, after a sign-off if the backend says it needs one."""
    if state["decision"] != "approve":
        return END
    return "sign_off" if state["needs_sign_off"] else "pay"


def build_claim_graph(
    backend: Backend,
    llm: BaseChatModel,
    instructions: str,
    checkpointer: BaseCheckpointSaver,
) -> CompiledStateGraph:
    """Build the graph that works one claim, saving its progress after every step."""
    tools = claim_tools(backend)
    with_tools = llm.bind_tools(tools)
    decider = llm.bind_tools([ClaimDecision], tool_choice="ClaimDecision")
    system = SystemMessage(instructions)

    def agent(state: ClaimState) -> dict[str, Any]:
        """Call the model with the conversation so far."""
        calls = count_call(state["model_calls"])
        reply = with_tools.invoke([system, *state["messages"]])
        return {"messages": [reply], "model_calls": calls}

    def decide(state: ClaimState) -> dict[str, Any]:
        """Turn the agent's work into a decision."""
        calls = count_call(state["model_calls"])
        ask = HumanMessage("Record your decision on this claim.")
        reply = cast(AIMessage, decider.invoke([system, *state["messages"], ask]))
        if not reply.tool_calls:
            raise ValueError("The model gave no decision")
        decision = ClaimDecision(**reply.tool_calls[0]["args"])
        return {"messages": [reply], "model_calls": calls, **decision.model_dump()}

    def record(state: ClaimState) -> dict[str, Any]:
        """Record the decision, and ask the claims system if it needs a sign-off."""
        claim = backend.record_decision(
            state["claim_id"],
            state["decision"],
            state["payout"],
            state["explanation"],
            state["policy_section"],
        )
        needs = claim.status == "awaiting_sign_off"
        text = "Decision recorded."
        if needs:
            text += " The payment is waiting for a handler's sign-off."
        return {"messages": [AIMessage(text)], "needs_sign_off": needs}

    def sign_off(state: ClaimState) -> dict[str, Any]:
        """Wait for a handler to sign off the payout."""
        interrupt(
            {
                "claim_id": state["claim_id"],
                "payout": state["payout"],
                "explanation": state["explanation"],
            }
        )
        return {}

    def pay(state: ClaimState) -> dict[str, Any]:
        """Pay the approved payout, which the claims system does once."""
        backend.pay(state["claim_id"], state["payout"])
        return {"messages": [AIMessage(f"Paid ${state['payout']}.")]}

    retry = retry_policy()
    builder = StateGraph(ClaimState)
    builder.add_node("agent", agent, retry_policy=retry)
    builder.add_node("tools", ToolNode(tools), retry_policy=retry)
    builder.add_node("decide", decide, retry_policy=retry)
    builder.add_node("record", record, retry_policy=retry)
    builder.add_node("sign_off", sign_off)
    builder.add_node("pay", pay, retry_policy=retry)
    builder.add_edge(START, "agent")
    builder.add_conditional_edges("agent", after_agent, ["tools", "decide"])
    builder.add_edge("tools", "agent")
    builder.add_edge("decide", "record")
    builder.add_conditional_edges("record", after_record, ["sign_off", "pay", END])
    builder.add_edge("sign_off", "pay")
    builder.add_edge("pay", END)
    return builder.compile(checkpointer=checkpointer)
