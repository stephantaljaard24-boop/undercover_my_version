import { ClaimPage } from "./ClaimPage";
import { InstructionsPage } from "./InstructionsPage";
import { QueuePage } from "./QueuePage";
import { useRoute } from "./route";

export function App() {
  const route = useRoute();

  return (
    <>
      <header className="topbar panel">
        <a className="brand" href="#/">
          UnderCover
        </a>
        <span className="tagline">The claims desk</span>
        <nav>
          <a href="#/">Queue</a>
          <a href="#/instructions">Instructions</a>
        </nav>
      </header>
      <main>
        {route.page === "queue" && <QueuePage />}
        {route.page === "claim" && (
          <ClaimPage key={route.claimId} claimId={route.claimId} />
        )}
        {route.page === "instructions" && <InstructionsPage />}
      </main>
    </>
  );
}
