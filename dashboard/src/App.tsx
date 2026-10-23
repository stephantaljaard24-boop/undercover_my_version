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
      </header>
      <main>{route.page === "queue" && <QueuePage />}</main>
    </>
  );
}
