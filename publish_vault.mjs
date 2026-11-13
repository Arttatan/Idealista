import { createCipheriv, pbkdf2Sync, randomBytes } from "node:crypto";
import { readFileSync, writeFileSync } from "node:fs";

const password = process.env.IDEALISTA_PASSWORD || "";
if (password.length < 10) {
  console.error("IDEALISTA_PASSWORD короче 10 символов. Пароль в файлы не пишется.");
  process.exit(1);
}

function encryptBytes(plain) {
  const salt = randomBytes(16);
  const iv = randomBytes(12);
  const key = pbkdf2Sync(password, salt, 250000, 32, "sha256");
  const cipher = createCipheriv("aes-256-gcm", key, iv);
  const packed = Buffer.concat([cipher.update(plain), cipher.final(), cipher.getAuthTag()]);
  return {
    v: 1,
    iter: 250000,
    salt: salt.toString("base64"),
    iv: iv.toString("base64"),
    data: packed.toString("base64"),
  };
}

const plain = readFileSync(0);
const vault = encryptBytes(plain);

const gistId = process.env.IDEALISTA_GIST_ID || "";
const syncToken = process.env.IDEALISTA_SYNC_TOKEN || "";
if (gistId && syncToken) {
  vault.sync = {
    gistId,
    fileName: process.env.IDEALISTA_GIST_FILE || "notes.vault.json",
    token: encryptBytes(Buffer.from(syncToken, "utf8")),
  };
}

writeFileSync("web/vault.json", JSON.stringify(vault));
