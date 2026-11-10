import assert from "node:assert/strict";
import { test } from "node:test";
import { answerMatches, gradeSwings } from "./match.ts";
import { decrypt, encrypt, seal, unseal } from "./secure.ts";
import { readMembership, tierFromCents, type PatreonIdentity } from "./tiers.ts";
import { easternLocalToIso, isoToEasternLocal } from "./time.ts";

const floors = { member: 500, producer: 1200, exec: 2500 };

test("answers match the way the overlay's Bullpen matcher does", () => {
  assert.ok(answerMatches("Roy Halladay", "Halladay|Doc Halladay", "  halladay "));
  assert.ok(answerMatches("Roy Halladay", "Halladay|Doc Halladay", "it was Roy Halladay!"));
  assert.ok(answerMatches("The Phillie Phanatic", "", "phillie phanatic"));
  assert.ok(answerMatches("1980", "", "1980"));
  assert.ok(!answerMatches("1980", "", "1980 or 1981"), "short answers must match exactly");
  assert.ok(!answerMatches("548", "", ""));
  assert.ok(!answerMatches("Jimmy Rollins", "Rollins|J-Roll", "Chase Utley"));
});

test("the earliest correct answer from a paying member scores", () => {
  const swings = [
    { id: "free-first", answer: "Rollins", createdAt: "2026-12-08T01:00:01Z", eligible: false },
    { id: "wrong", answer: "Utley", createdAt: "2026-12-08T01:00:02Z", eligible: true },
    { id: "late", answer: "Jimmy Rollins", createdAt: "2026-12-08T01:00:09Z", eligible: true },
    { id: "member", answer: "j-roll", createdAt: "2026-12-08T01:00:04Z", eligible: true },
  ];
  const r = gradeSwings(swings, "Jimmy Rollins", "Rollins|J-Roll");
  assert.equal(r.winnerId, "member");
  assert.equal(r.correct.get("free-first"), true);
  assert.equal(r.correct.get("wrong"), false);
  assert.equal(gradeSwings([swings[0], swings[1]], "Jimmy Rollins", "Rollins").winnerId, null);
});

test("tier floors", () => {
  assert.equal(tierFromCents(0, floors), 0);
  assert.equal(tierFromCents(499, floors), 0);
  assert.equal(tierFromCents(500, floors), 1);
  assert.equal(tierFromCents(1200, floors), 2);
  assert.equal(tierFromCents(2500, floors), 3);
  assert.equal(tierFromCents(10000, floors), 3);
});

function identity(members: { campaign: string; tiers: string[]; status: string | null }[]): PatreonIdentity {
  return {
    data: { type: "user", id: "u1", attributes: { full_name: "Pat Fan" } },
    included: [
      ...members.map((m, i) => ({
        type: "member",
        id: `m${i}`,
        attributes: { patron_status: m.status },
        relationships: {
          campaign: { data: { type: "campaign", id: m.campaign } },
          currently_entitled_tiers: { data: m.tiers.map((id) => ({ type: "tier", id })) },
        },
      })),
      { type: "tier", id: "t5", attributes: { amount_cents: 500 } },
      { type: "tier", id: "t12", attributes: { amount_cents: 1200 } },
      { type: "tier", id: "t25", attributes: { amount_cents: 2500 } },
    ],
  };
}

test("membership is read from the entitled tiers of our campaign only", () => {
  const producer = readMembership(identity([{ campaign: "ours", tiers: ["t12"], status: "active_patron" }]), "ours");
  assert.deepEqual(producer, { patreonUserId: "u1", name: "Pat Fan", patronStatus: "active_patron", entitledCents: 1200 });

  const elsewhere = readMembership(identity([{ campaign: "other", tiers: ["t25"], status: "active_patron" }]), "ours");
  assert.equal(elsewhere.entitledCents, 0);

  const lapsed = readMembership(identity([{ campaign: "ours", tiers: [], status: "former_patron" }]), "ours");
  assert.equal(lapsed.entitledCents, 0);

  const follower = readMembership({ data: { type: "user", id: "u2", attributes: {} } }, "ours");
  assert.deepEqual(follower, { patreonUserId: "u2", name: null, patronStatus: null, entitledCents: 0 });
});

test("session seal rejects tampering; token encryption round-trips", () => {
  const secret = "x".repeat(40);
  const sealed = seal("user-id.123", secret);
  assert.equal(unseal(sealed, secret), "user-id.123");
  assert.equal(unseal(sealed.replace("user-id", "admin-id"), secret), null);
  assert.equal(unseal(sealed, "y".repeat(40)), null);
  assert.equal(unseal("nonsense", secret), null);

  const blob = encrypt("refresh-token", secret);
  assert.notEqual(blob, encrypt("refresh-token", secret), "fresh IV each time");
  assert.equal(decrypt(blob, secret), "refresh-token");
  assert.equal(decrypt(blob, "y".repeat(40)), null);
  assert.equal(decrypt("garbage", secret), null);
});

test("Eastern show times convert in winter and summer", () => {
  assert.equal(easternLocalToIso("2026-12-08T20:00"), "2026-12-09T01:00:00.000Z");
  assert.equal(easternLocalToIso("2027-03-24T20:00"), "2027-03-25T00:00:00.000Z");
  assert.equal(easternLocalToIso(""), null);
  assert.equal(isoToEasternLocal("2026-12-09T01:00:00.000Z"), "2026-12-08T20:00");
  assert.equal(isoToEasternLocal(null), "");
});
