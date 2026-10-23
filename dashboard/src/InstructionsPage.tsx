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
        What the UnderCover Agent is told on every claim. Read only.
      </p>
      {instructions === null ? (
        <p className="muted">
          {failed
            ? "The instructions could not be loaded."
            : "Loading the instructions."}
        </p>
      ) : (
        <pre className="panel instructions">{instructions}</pre>
      )}
    </>
  );
}
