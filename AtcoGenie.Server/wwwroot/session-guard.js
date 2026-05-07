/**
 * AtcoGenie -- SSE Session Guard v1
 * ====================================
 * Prevents streaming state (thinking indicator, partial responses, final reply)
 * from bleeding into a different chat when the user switches sessions mid-stream.
 *
 * Root cause: The React SPA uses a single global streaming state. When the user
 * switches chats while a response is being generated, the SSE reader is still
 * open and events keep arriving -- the React state machine applies them to the
 * NOW-ACTIVE chat instead of the one that originated the request.
 *
 * Fix architecture:
 *  1. C# proxy (Program.cs) injects "session_id" into every SSE data event.
 *  2. This script patches window.fetch BEFORE the React bundle loads.
 *  3. For every /api/query fetch it wraps the SSE response in a TransformStream.
 *  4. Events whose session_id != the MOST RECENTLY STARTED session are dropped.
 *
 * Result: Parallel queries in multiple tabs/sessions are fully isolated.
 *         Switching chats mid-stream does not pollute the new chat.
 */
(function patchFetchForSessionIsolation() {
  "use strict";

  // The session_id of the MOST RECENTLY INITIATED query.
  // Any SSE event from an older session is silently discarded.
  let _activeSessionId = null;

  const _originalFetch = window.fetch.bind(window);

  window.fetch = async function (input, init) {
    const url = (typeof input === "string" ? input : (input?.url ?? "")).split("?")[0];

    // Only intercept the streaming query endpoint
    if (!url.endsWith("/api/query")) {
      return _originalFetch(input, init);
    }

    // Extract session_id from the request body
    let requestSessionId = null;
    try {
      const body = init?.body;
      if (typeof body === "string") {
        const parsed = JSON.parse(body);
        if (parsed.sessionId != null) requestSessionId = String(parsed.sessionId);
      }
    } catch { /* ignore parse errors */ }

    // Mark this as the active session -- any previous stream is now stale
    if (requestSessionId) {
      _activeSessionId = requestSessionId;
      console.debug("[AtcoGenie:SessionGuard] Active session ->", _activeSessionId);
    }

    const response = await _originalFetch(input, init);

    // Only wrap SSE (text/event-stream) responses
    const contentType = response.headers.get("content-type") ?? "";
    if (!contentType.includes("event-stream")) {
      return response;
    }

    // Pipe the response body through a filter that drops stale-session events
    const { readable, writable } = new TransformStream();
    const pipeWriter = writable.getWriter();
    const bodyReader = response.body.getReader();
    const decoder = new TextDecoder();
    const encoder = new TextEncoder();

    // Run the pipe in the background (do NOT await -- returns filtered stream immediately)
    (async () => {
      let lineBuffer = "";
      try {
        while (true) {
          const { done, value } = await bodyReader.read();
          if (done) {
            // Flush any remaining buffered line
            if (lineBuffer) {
              await pipeWriter.write(encoder.encode(lineBuffer + "\n"));
            }
            await pipeWriter.close();
            break;
          }

          lineBuffer += decoder.decode(value, { stream: true });
          const lines = lineBuffer.split("\n");
          lineBuffer = lines.pop(); // last fragment may be incomplete

          for (const line of lines) {
            // Non-data lines (keepalives, blank separators) pass through
            if (!line.startsWith("data: ")) {
              await pipeWriter.write(encoder.encode(line + "\n"));
              continue;
            }

            // Parse and check session_id
            let shouldDrop = false;
            try {
              const payload = JSON.parse(line.slice(6));
              const eventSession = payload.session_id;

              if (eventSession && _activeSessionId && eventSession !== _activeSessionId) {
                console.debug(
                  "[AtcoGenie:SessionGuard] Dropped stale event",
                  `type=${payload.type}`,
                  `from=${eventSession}`,
                  `active=${_activeSessionId}`
                );
                shouldDrop = true;
              }
            } catch { /* non-JSON or malformed -- pass through safely */ }

            if (!shouldDrop) {
              await pipeWriter.write(encoder.encode(line + "\n"));
            }
          }
        }
      } catch (err) {
        console.warn("[AtcoGenie:SessionGuard] Pipe error:", err);
        try { await pipeWriter.abort(err); } catch { /* already closed */ }
      }
    })();

    // Return a new Response backed by the filtered readable stream
    return new Response(readable, {
      status: response.status,
      statusText: response.statusText,
      headers: response.headers,
    });
  };

  console.log("[AtcoGenie:SessionGuard] fetch interceptor installed.");
})();
