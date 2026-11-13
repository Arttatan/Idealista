import { createCipheriv, pbkdf2Sync, randomBytes } from "node:crypto";
import { readFileSync } from "node:fs";

const password = process.env.IDEALISTA_PASSWORD || "";
if (password.length < 10) {
  console.error("IDEALISTA_PASSWORD слишком короткий");
  process.exit(1);
}
const plain = readFileSync(0);
const salt = randomBytes(16);
const iv = randomBytes(12);
const key = pbkdf2Sync(password, salt, 250000, 32, "sha256");
const cipher = createCipheriv("aes-256-gcm", key, iv);
const packed = Buffer.concat([cipher.update(plain), cipher.final(), cipher.getAuthTag()]);
process.stdout.write(JSON.stringify({
  v: 1,
  iter: 250000,
  salt: salt.toString("base64"),
  iv: iv.toString("base64"),
  data: packed.toString("base64"),
}));
