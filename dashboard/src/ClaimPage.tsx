import { useCallback } from "react";
import { fetchClaimView } from "./api";
import type {
  ClaimDetail,
  ClaimView,
  Customer,
  Policy,
  SectionRead,
  Step,
} from "./api";
import {
  DOCUMENT_LABELS,
  formatDate,
  formatType,
  STATUS_LABELS,
  VERDICT_LABELS,
} from "./labels";
import { formatCents } from "./money";
import { usePolling } from "./usePolling";

const WORKING_POLL_MS = 2000;
const WAITING_POLL_MS = 3000;

const STEP_LABELS: Record<Step["kind"], string> = {
  tool_call: "Tool call",
  tool_result: "Tool result",
  reply: "Reply",
  error: "Error",
};

/**
 * Keep watching a claim until the agent has decided it and given its final
 * reply. The agent pays and replies after it records its decision.
 */
function pollDelay({ claim, steps }: ClaimView): number | null {
  if (claim.status === "needs_handler") return null;
  if (claim.status === "waiting") return WAITING_POLL_MS;
  const finished = claim.decision !== null && steps.at(-1)?.kind === "reply";
  return finished ? null : WORKING_POLL_MS;
}

function PaymentLine({ claim }: Readonly<{ claim: ClaimDetail }>) {
  if (claim.decision?.decision !== "approve") return null;
  if (claim.payment) return <p>Paid {formatCents(claim.payment.amount)}.</p>;
  if (claim.status === "awaiting_sign_off")
    return (
      <p className="blocked">
        Payment blocked: waiting for a handler&apos;s sign-off.
      </p>
    );
  return <p>Not paid yet.</p>;
}

function DecisionPanel({ claim }: Readonly<{ claim: ClaimDetail }>) {
  const { decision } = claim;
  return (
    <section className="panel card">
      <h2>Decision</h2>
      {decision ? (
        <>
          <p>
            <span className={`pill decision-${decision.decision}`}>
              {VERDICT_LABELS[decision.decision]}
            </span>
            {decision.decision === "approve" && (
              <span className="mono payout">
                {formatCents(decision.payout)}
              </span>
            )}
          </p>
          <p>{decision.explanation}</p>
          <p className="muted small">
            Policy section: {decision.policy_section}
          </p>
          <PaymentLine claim={claim} />
        </>
      ) : (
        <p className="muted">
          {claim.status === "in_progress"
            ? "The agent is working on this claim."
            : "No decision yet."}
        </p>
      )}
    </section>
  );
}

function PolicyPanel({ policy }: Readonly<{ policy: Policy }>) {
  return (
    <section className="panel card">
      <h2>Policy</h2>
      <dl>
        <dt>Policy</dt>
        <dd className="mono">{policy.policy_id}</dd>
        <dt>Plan</dt>
        <dd>{formatType(policy.plan)}</dd>
        <dt>Add-ons</dt>
        <dd>
          {policy.add_ons.length > 0
            ? policy.add_ons.map(formatType).join(", ")
            : "None"}
        </dd>
        <dt>Trip</dt>
        <dd>
          {policy.trip.destination}, {formatDate(policy.trip.departs_on)} to{" "}
          {formatDate(policy.trip.returns_on)}
        </dd>
        <dt>Trip cost</dt>
        <dd className="mono">{formatCents(policy.trip.trip_cost)}</dd>
        <dt>Travelers</dt>
        <dd>{policy.travelers.join(", ")}</dd>
      </dl>
    </section>
  );
}

function CustomerPanel({ customer }: Readonly<{ customer: Customer }>) {
  return (
    <section className="panel card">
      <h2>Customer</h2>
      <p>
        {customer.name}{" "}
        <span className="muted small">
          since {formatDate(customer.customer_since)}
        </span>
      </p>
      <h3>Earlier claims</h3>
      {customer.previous_claims.length === 0 ? (
        <p className="muted">None.</p>
      ) : (
        <ul>
          {customer.previous_claims.map((earlier) => (
            <li key={earlier.claim_id}>
              <span className="mono">{earlier.claim_id}</span>{" "}
              {formatDate(earlier.filed_on)}: {earlier.summary},{" "}
              {earlier.outcome}
              {earlier.amount_paid > 0 && (
                <>, paid {formatCents(earlier.amount_paid)}</>
              )}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function StepsPanel({ steps }: Readonly<{ steps: Step[] }>) {
  return (
    <section className="panel card">
      <h2>What the agent did</h2>
      {steps.length === 0 ? (
        <p className="muted">Nothing yet.</p>
      ) : (
        <ol className="steps">
          {steps.map((step) => (
            <li key={step.id} className={`step-${step.kind}`}>
              <span className="step-kind">{STEP_LABELS[step.kind]}</span>
              <pre>{step.text}</pre>
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}

function ReadsPanel({ reads }: Readonly<{ reads: SectionRead[] }>) {
  return (
    <section className="panel card">
      <h2>What the agent read</h2>
      {reads.length === 0 ? (
        <p className="muted">Nothing read yet.</p>
      ) : (
        <ul className="reads">
          {reads.map((read) => (
            <li key={`${read.document}-${read.section}`}>
              {DOCUMENT_LABELS[read.document]}, section {read.section}:{" "}
              {read.title}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function ClaimPanel({ claim }: Readonly<{ claim: ClaimDetail }>) {
  return (
    <section className="panel card">
      <h2>Claim</h2>
      <p className="muted small">
        {formatType(claim.claim_type)}, submitted{" "}
        {formatDate(claim.submitted_on)}. Incident on{" "}
        {formatDate(claim.incident_date)} in {claim.incident_location}.
      </p>
      <p>{claim.story}</p>
      <h3>Items claimed</h3>
      <table className="items">
        <tbody>
          {claim.items.map((item) => (
            <tr key={item.description}>
              <td>{item.description}</td>
              <td className="amount mono">{formatCents(item.amount)}</td>
            </tr>
          ))}
          <tr className="total">
            <td>Total claimed</td>
            <td className="amount mono">{formatCents(claim.amount_claimed)}</td>
          </tr>
        </tbody>
      </table>
      <h3>Documents</h3>
      {claim.documents.map((document) => (
        <article key={document.name} className="document">
          <h4>
            {document.name}{" "}
            <span className="muted small">{formatType(document.type)}</span>
          </h4>
          <p>{document.content}</p>
        </article>
      ))}
    </section>
  );
}

export function ClaimPage({ claimId }: Readonly<{ claimId: string }>) {
  const load = useCallback(() => fetchClaimView(claimId), [claimId]);
  const { data, failed } = usePolling(load, pollDelay);

  if (!data) {
    return (
      <p className="muted">
        {failed ? "The claim could not be loaded." : "Loading the claim."}
      </p>
    );
  }

  const { claim, policy, customer, steps, reads } = data;
  return (
    <>
      <p>
        <a href="#/">Back to the queue</a>
      </p>
      <h1>
        <span className="mono">{claim.claim_id}</span>{" "}
        <span className={`pill status-${claim.status}`}>
          {STATUS_LABELS[claim.status]}
        </span>
      </h1>
      <p className="muted">{claim.summary}</p>
      <div className="columns">
        <ClaimPanel claim={claim} />
        <div className="side">
          <DecisionPanel claim={claim} />
          <ReadsPanel reads={reads} />
          <PolicyPanel policy={policy} />
          <CustomerPanel customer={customer} />
        </div>
      </div>
      <StepsPanel steps={steps} />
    </>
  );
}
