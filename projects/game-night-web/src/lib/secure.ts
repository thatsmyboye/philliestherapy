import { createCipheriv, createDecipheriv, createHash, createHmac, randomBytes, timingSafeEqual } from "node:crypto";

/** Constant-time string comparison that tolerates different lengths. */
export function safeEqual(a: string, b: string): boolean {
  const ha = createHash("sha256").update(a).digest();
  const hb = createHash("sha256").update(b).digest();
  return timingSafeEqual(ha, hb);
}

export function randomToken(bytes = 24): string {
  return randomBytes(bytes).toString("base64url");
}

export function sign(value: string, secret: string): string {
  return createHmac("sha256", secret).update(value).digest("base64url");
}

/** `payload.signature`, where payload itself contains no dots that matter to us. */
export function seal(payload: string, secret: string): string {
  return `${payload}.${sign(payload, secret)}`;
}

export function unseal(sealed: string, secret: string): string | null {
  const i = sealed.lastIndexOf(".");
  if (i <= 0) return null;
  const payload = sealed.slice(0, i);
  return safeEqual(sealed.slice(i + 1), sign(payload, secret)) ? payload : null;
}

function encKey(secret: string): Buffer {
  return createHash("sha256").update(`gn-token-encryption:${secret}`).digest();
}

/** AES-256-GCM. Output: base64url(iv | tag | ciphertext). */
export function encrypt(plain: string, secret: string): string {
  const iv = randomBytes(12);
  const cipher = createCipheriv("aes-256-gcm", encKey(secret), iv);
  const body = Buffer.concat([cipher.update(plain, "utf8"), cipher.final()]);
  return Buffer.concat([iv, cipher.getAuthTag(), body]).toString("base64url");
}

export function decrypt(blob: string, secret: string): string | null {
  try {
    const raw = Buffer.from(blob, "base64url");
    const decipher = createDecipheriv("aes-256-gcm", encKey(secret), raw.subarray(0, 12));
    decipher.setAuthTag(raw.subarray(12, 28));
    return Buffer.concat([decipher.update(raw.subarray(28)), decipher.final()]).toString("utf8");
  } catch {
    return null;
  }
}
