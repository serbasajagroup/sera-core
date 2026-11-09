// Pure helpers for an owner-allowlisted WhatsApp bridge (for example one built
// on Baileys). No network or WhatsApp dependency: everything here is testable.

export const MAX_MEDIA = 16 * 1024 * 1024;

/** Digits-only international number, or null. Accepts JIDs like 62812...@s.whatsapp.net. */
export function phone(raw) {
  const value = String(raw || '').split('@')[0].split(':')[0].replace(/^\+/, '');
  return /^[1-9]\d{5,14}$/.test(value) ? value : null;
}

/** True only for one-to-one chats (no groups, broadcasts or newsletters). */
export function directJid(jid) {
  return typeof jid === 'string' && /^\d+(?::\d+)?@(s\.whatsapp\.net|lid)$/.test(jid);
}

function candidates(key) {
  if (!key || key.fromMe || !directJid(key.remoteJid)) return [];
  const values = key.remoteJid.endsWith('@s.whatsapp.net') ? [key.remoteJid] : [key.remoteJidAlt];
  return values.filter(j => typeof j === 'string' && j.endsWith('@s.whatsapp.net')).map(phone).filter(Boolean);
}

/**
 * Returns the sender's number if, and only if, the message comes from exactly
 * one allowlisted number in a direct chat. Ambiguous identities are rejected.
 * @param {object} key  message key ({remoteJid, remoteJidAlt, fromMe})
 * @param {Set<string>} allowed  allowlisted numbers
 * @param {string} [resolved]  phone number resolved for a @lid identity
 */
export function permitted(key, allowed, resolved) {
  if (!key || key.fromMe || !directJid(key.remoteJid)) return null;
  const values = candidates(key);
  if (key.remoteJid.endsWith('@lid') && phone(resolved)) values.push(phone(resolved));
  const unique = [...new Set(values)];
  return unique.length === 1 && allowed.has(unique[0]) ? unique[0] : null;
}

/** File name safe to write to disk: no path parts, no hidden files, limited charset. */
export function safeName(name, ext = '.bin') {
  const value = String(name || 'attachment' + ext).split(/[\\/]/).pop()
    .replace(/[^\p{L}\p{N} ._()-]/gu, '_').slice(0, 120);
  return !value || value.startsWith('.') ? 'attachment' + ext : value;
}

export function pollOptions(value) {
  if (!value || typeof value.name !== 'string' || !value.name.trim() || value.name.length > 180 ||
      !Array.isArray(value.values) || value.values.length < 2 || value.values.length > 8 ||
      value.values.some(s => typeof s !== 'string' || !s.trim() || s.length > 90) ||
      new Set(value.values).size !== value.values.length) throw new Error('invalid_poll');
  return { name: value.name, values: value.values, selectableCount: 1 };
}

/** Build an outbound message with strict type and size limits. */
export function outboundPayload(value, buffer) {
  if (value.poll) return { poll: pollOptions(value.poll) };
  if (buffer) {
    if (buffer.length > MAX_MEDIA) throw new Error('media_too_large');
    const caption = String(value.text || '').slice(0, 1000);
    if (value.kind === 'audio') return { audio: buffer, mimetype: 'audio/ogg; codecs=opus', ptt: true };
    if (value.kind === 'image' && /^image\/(png|jpeg|webp)$/.test(value.mime)) return { image: buffer, mimetype: value.mime, caption };
    if (value.kind === 'video' && value.mime === 'video/mp4') return { video: buffer, mimetype: value.mime, caption };
    return { document: buffer, fileName: safeName(value.name), mimetype: String(value.mime || 'application/octet-stream'), caption };
  }
  if (typeof value.text !== 'string' || !value.text.trim() || value.text.length > 4000) throw new Error('invalid_message');
  return { text: value.text };
}
