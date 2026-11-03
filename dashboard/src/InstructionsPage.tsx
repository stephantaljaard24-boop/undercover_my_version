import { fetchInstructions } from "./api";
import { usePolling } from "./usePolling";

function loadOnce(): null {
  return null;
}

export function InstructionsPage() {
  const { data: instructions, failed } = usePolling(
    fetchInstructions,
    loadOnce,
  );

  return (
    <>
      <h1>Agent instructions</h1>
      <p className="muted">
        What the UnderCover Agent is told, for running the queue and for working
        a claim. Read only.
      </p>
      {instructions === null ? (
        <p className="muted">
          {failed
            ? "The instructions could not be loaded."
            : "Loading the instructions."}
        </p>
      ) : (
        <>
          <h2>Running the queue</h2>
          <pre className="panel instructions">{instructions.queue}</pre>
          <h2>Working a claim</h2>
          <pre className="panel instructions">{instructions.claim}</pre>
        </>
      )}
    </>
  );
}
