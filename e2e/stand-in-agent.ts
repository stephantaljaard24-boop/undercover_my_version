// Stands in for the agent's service in the end-to-end tests. It keeps the claims
// the backend told it about and lists them at GET /received.
import { createServer } from "node:http";

const PORT = 8003;
const RESUME = /^\/api\/claims\/([^/]+)\/resume$/;
const received: string[] = [];

createServer((request, response) => {
  const resumed = RESUME.exec(request.url ?? "");
  if (request.method === "POST" && resumed?.[1]) {
    received.push(resumed[1]);
    response.writeHead(202).end();
  } else if (request.url === "/received") {
    response.writeHead(200, { "Content-Type": "application/json" });
    response.end(JSON.stringify(received));
  } else {
    response.writeHead(200).end("ok");
  }
}).listen(PORT, "127.0.0.1");
