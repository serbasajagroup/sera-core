import test from 'node:test';
import assert from 'node:assert/strict';
import { phone, directJid, permitted, safeName, pollOptions, outboundPayload, MAX_MEDIA } from './whatsapp-protocol.mjs';

const allowed = new Set(['6281200000001']);

test('phone normalises JIDs and rejects junk', () => {
  assert.equal(phone('+6281200000001'), '6281200000001');
  assert.equal(phone('6281200000001:3@s.whatsapp.net'), '6281200000001');
  assert.equal(phone('081200000001'), null);
  assert.equal(phone('abc'), null);
});

test('only direct chats are accepted', () => {
  assert.ok(directJid('6281200000001@s.whatsapp.net'));
  assert.ok(directJid('12345@lid'));
  assert.ok(!directJid('120363000000000000@g.us'));
  assert.ok(!directJid('status@broadcast'));
});

test('permitted accepts only one allowlisted sender', () => {
  assert.equal(permitted({ remoteJid: '6281200000001@s.whatsapp.net' }, allowed), '6281200000001');
  assert.equal(permitted({ remoteJid: '6281200000002@s.whatsapp.net' }, allowed), null);
  assert.equal(permitted({ remoteJid: '6281200000001@s.whatsapp.net', fromMe: true }, allowed), null);
  assert.equal(permitted({ remoteJid: '120363@g.us' }, allowed), null);
});

test('permitted rejects ambiguous @lid identities', () => {
  const key = { remoteJid: '999@lid', remoteJidAlt: '6281200000001@s.whatsapp.net' };
  assert.equal(permitted(key, allowed), '6281200000001');
  assert.equal(permitted(key, allowed, '6281200000002'), null);
});

test('safeName strips paths and hidden names', () => {
  assert.equal(safeName('../../etc/passwd'), 'passwd');
  assert.equal(safeName('.env'), 'attachment.bin');
  assert.equal(safeName('a/b\\c<d>.pdf'), 'c_d_.pdf');
});

test('poll and outbound validation', () => {
  assert.throws(() => pollOptions({ name: 'x', values: ['a'] }), /invalid_poll/);
  assert.throws(() => pollOptions({ name: 'x', values: ['a', 'a'] }), /invalid_poll/);
  assert.deepEqual(pollOptions({ name: 'Pick', values: ['a', 'b'] }).selectableCount, 1);
  assert.throws(() => outboundPayload({ text: '' }), /invalid_message/);
  assert.throws(() => outboundPayload({ kind: 'document' }, Buffer.alloc(MAX_MEDIA + 1)), /media_too_large/);
  assert.equal(outboundPayload({ kind: 'image', mime: 'image/svg+xml', name: 'x.svg' }, Buffer.from('x')).document.length, 1);
});
