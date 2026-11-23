"""The tools of the claim helper. Each one asks the backend for a single thing."""

from langchain_core.tools import BaseTool

from agent.harness.tools import text_tool
from agent.undercover.backend import Backend, Benefit, PayoutLine


def claim_tools(backend: Backend) -> list[BaseTool]:
    """Build the claim helper's tools on a backend."""

    @text_tool
    def get_claim(claim_id: str) -> str:
        """Get a claim in full: the story, the items claimed and the documents."""
        return backend.claim_text(claim_id)

    @text_tool
    def get_policy(policy_id: str) -> str:
        """Get a policy: the plan, add-ons, trip dates, trip cost and travelers."""
        return backend.policy_text(policy_id)

    @text_tool
    def get_customer(customer_id: str) -> str:
        """Get a customer and their earlier claims."""
        return backend.customer_text(customer_id)

    @text_tool
    def get_contents(document: str) -> str:
        """List the numbered sections of a document: policy_wording or claims_manual."""
        return backend.contents(document)

    @text_tool
    def read_section(claim_id: str, document: str, section: str) -> str:
        """Read a section of policy_wording or claims_manual by number, such as "9"."""
        return backend.read_section(claim_id, document, section)

    @text_tool
    def calculate_payout(
        claim_id: str,
        benefit: Benefit,
        lines: list[PayoutLine],
        paid_by_others: str,
    ) -> str:
        """Work out the payout on an approved claim with UnderCover's payout rules.
        Give the benefit the claim is paid under, one line for each covered item or
        expense (leave out any excluded ones), and anything a carrier, hotel or other
        party has paid or refunded for the same loss as a dollar amount such as
        "100.00", or "0.00". It returns the calculation, the payout and whether the
        payout needs a handler's sign-off."""
        result = backend.calculate_payout(claim_id, benefit, lines, paid_by_others)
        return result.model_dump_json(indent=2)

    return [
        get_claim,
        get_policy,
        get_customer,
        get_contents,
        read_section,
        calculate_payout,
    ]
