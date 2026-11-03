import { fetchQueueView } from "./api";
import type { Run } from "./api";
import { formatCents } from "./money";
import {
  formatDate,
  formatType,
  STATUS_LABELS,
  STATUSES,
  TODO_LABELS,
  VERDICT_LABELS,
} from "./labels";
import { usePolling } from "./usePolling";

const QUEUE_POLL_MS = 3000;

function keepPolling(): number {
  return QUEUE_POLL_MS;
}

function RunPanel({ run }: Readonly<{ run: Run }>) {
  return (
    <section className="panel card run" aria-label="Current run">
      <h2>Current run</h2>
      <p className="muted small">
        Up to {run.claim_limit} {run.claim_limit === 1 ? "claim" : "claims"}.{" "}
        {run.finished ? "Finished." : "Running."}
      </p>
      {run.todos.length === 0 ? (
        <p className="muted">No to-do list yet.</p>
      ) : (
        <ul className="todos">
          {run.todos.map((todo) => (
            <li key={todo.text}>
              <span className={`pill todo-${todo.status}`}>
                {TODO_LABELS[todo.status]}
              </span>
              {todo.text}
            </li>
          ))}
        </ul>
      )}
      {run.summary && (
        <>
          <h3>Summary</h3>
          <p className="summary">{run.summary}</p>
        </>
      )}
    </section>
  );
}

export function QueuePage() {
  const { data, failed } = usePolling(fetchQueueView, keepPolling);

  if (!data) {
    return (
      <p className="muted">
        {failed ? "The queue could not be loaded." : "Loading the queue."}
      </p>
    );
  }

  const { claims, run } = data;
  return (
    <>
      <h1>Claims queue</h1>
      {run && <RunPanel run={run} />}
      <section className="counts" aria-label="Claims by status">
        {STATUSES.map((status) => (
          <div key={status} className={`panel count status-${status}`}>
            <span className="number">
              {claims.filter((claim) => claim.status === status).length}
            </span>
            <span>{STATUS_LABELS[status]}</span>
          </div>
        ))}
      </section>
      <table className="panel queue">
        <thead>
          <tr>
            <th>Claim</th>
            <th>Customer</th>
            <th>Summary</th>
            <th>Submitted</th>
            <th className="amount">Claimed</th>
            <th>Status</th>
            <th>Decision</th>
          </tr>
        </thead>
        <tbody>
          {claims.map((claim) => (
            <tr key={claim.claim_id}>
              <td>
                <a
                  className="mono stretched"
                  href={`#/claims/${claim.claim_id}`}
                >
                  {claim.claim_id}
                </a>
                <div className="muted small">
                  {formatType(claim.claim_type)}
                </div>
              </td>
              <td>{claim.customer_name}</td>
              <td>{claim.summary}</td>
              <td className="nowrap">{formatDate(claim.submitted_on)}</td>
              <td className="amount mono">
                {formatCents(claim.amount_claimed)}
              </td>
              <td>
                <span className={`pill status-${claim.status}`}>
                  {STATUS_LABELS[claim.status]}
                </span>
              </td>
              <td>
                {claim.decision && (
                  <span className={`pill decision-${claim.decision}`}>
                    {VERDICT_LABELS[claim.decision]}
                  </span>
                )}
                {claim.decision === "approve" && claim.payout !== null && (
                  <>
                    {" "}
                    <span className="mono payout">
                      {formatCents(claim.payout)}
                    </span>
                  </>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </>
  );
}
