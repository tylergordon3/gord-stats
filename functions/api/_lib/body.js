/**
 * The JSON body of a small write, read with a ceiling.
 *
 * Every write the site takes is a few hundred bytes - a link, a week's picks,
 * a name. A body much bigger than that is not one of ours, and is refused
 * (413) before it is parsed: on the length it declares, and again on what
 * actually arrived, since a chunked body declares none.
 */
import { json } from "./session.js";

/** -> { data } | { error: Response }. `data` is whatever JSON was sent. */
export async function readBody(request, max) {
  const said = Number(request.headers.get("content-length") || 0);
  if (said > max) return { error: json({ ok: false, error: "too large" }, 413) };
  let text;
  try {
    text = await request.text();
  } catch {
    return { error: json({ ok: false, error: "expected JSON" }, 400) };
  }
  if (text.length > max) return { error: json({ ok: false, error: "too large" }, 413) };
  try {
    return { data: JSON.parse(text) };
  } catch {
    return { error: json({ ok: false, error: "expected JSON" }, 400) };
  }
}
