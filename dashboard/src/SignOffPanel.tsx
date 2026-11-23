import { useState } from "react";
import { fetchHandlers, signOff } from "./api";
import { usePolling } from "./usePolling";

const stopAfterFirstLoad = () => null;

/** Lets a handler sign off a payout that is waiting for one. */
export function SignOffPanel({
  claimId,
  onSignedOff,
}: Readonly<{ claimId: string; onSignedOff: () => void }>) {
  const { data } = usePolling(fetchHandlers, stopAfterFirstLoad);
  const [chosen, setChosen] = useState("");
  const [saving, setSaving] = useState(false);
  const [failed, setFailed] = useState(false);

  const handlers = (data ?? []).filter(
    (handler) => handler.can_approve_over_limit,
  );
  const handlerId = chosen || handlers[0]?.handler_id || "";

  const submit = () => {
    setSaving(true);
    setFailed(false);
    signOff(claimId, handlerId)
      .then(onSignedOff)
      .catch(() => {
        setFailed(true);
      })
      .finally(() => {
        setSaving(false);
      });
  };

  return (
    <div className="sign-off">
      <label htmlFor="handler">Sign off as</label>
      <select
        id="handler"
        value={handlerId}
        onChange={(event) => {
          setChosen(event.target.value);
        }}
      >
        {handlers.map((handler) => (
          <option key={handler.handler_id} value={handler.handler_id}>
            {handler.name}
          </option>
        ))}
      </select>
      <button
        type="button"
        className="button"
        disabled={saving || handlerId === ""}
        onClick={submit}
      >
        Sign off
      </button>
      {failed && (
        <p className="small error">The sign-off could not be saved.</p>
      )}
    </div>
  );
}
