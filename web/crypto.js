/**
 * TouchLink E2E Crypto Helpers for Web PWA (Sprint 2.2).
 * Sử dụng WebCrypto Subtle API chuẩn: HKDF-SHA256 + AES-GCM 256-bit.
 * Chống nghe lén qua relay, chống replay với bộ đếm nonce tăng dần.
 */

const ENC = new TextEncoder();
const DEC = new TextDecoder();

/**
 * Nối các Uint8Array lại với nhau.
 * @param  {...Uint8Array} arrays
 * @returns {Uint8Array}
 */
export function concatBytes(...arrays) {
  let total = 0;
  for (const a of arrays) total += a.byteLength;
  const res = new Uint8Array(total);
  let offset = 0;
  for (const a of arrays) {
    res.set(a, offset);
    offset += a.byteLength;
  }
  return res;
}

/**
 * Đóng gói số nguyên counter 64-bit Big-Endian (8 bytes).
 * @param {number} counter
 * @returns {Uint8Array}
 */
export function packUint64BE(counter) {
  const buf = new Uint8Array(8);
  const view = new DataView(buf.buffer);
  view.setBigUint64(0, BigInt(counter), false);
  return buf;
}

/**
 * Đọc số nguyên counter 64-bit Big-Endian (8 bytes).
 * @param {Uint8Array} bytes
 * @returns {number}
 */
export function unpackUint64BE(bytes) {
  const view = new DataView(bytes.buffer, bytes.byteOffset, 8);
  return Number(view.getBigUint64(0, false));
}

/**
 * Dẫn xuất khóa phiên AES-GCM 256-bit từ mật khẩu và transcript bằng HKDF-SHA256.
 * Khớp 100% với derive_passcode_key() trong desktop/security/e2e.py.
 * @param {string} passcode
 * @param {Uint8Array|string} transcript
 * @returns {Promise<{ key: CryptoKey, rawKey: Uint8Array, transcriptBytes: Uint8Array }>}
 */
export async function setupE2EKey(passcode, transcript) {
  const transcriptBytes = typeof transcript === 'string' ? ENC.encode(transcript) : transcript;
  const keyMaterial = ENC.encode(String(passcode || ''));
  const salt = ENC.encode('touchlink-e2e-passcode');
  const info = concatBytes(ENC.encode('touchlink-passcode-v1'), transcriptBytes);

  const baseKey = await crypto.subtle.importKey(
    'raw',
    keyMaterial,
    'HKDF',
    false,
    ['deriveBits']
  );

  const rawBits = await crypto.subtle.deriveBits(
    {
      name: 'HKDF',
      hash: 'SHA-256',
      salt: salt,
      info: info,
    },
    baseKey,
    256
  );

  const rawSharedSecret = new Uint8Array(rawBits);
  const aeadSalt = rawSharedSecret.slice(0, 16);
  const aeadInfo = concatBytes(ENC.encode('touchlink-e2e-v1|key|'), transcriptBytes);

  const sharedBaseKey = await crypto.subtle.importKey(
    'raw',
    rawSharedSecret,
    'HKDF',
    false,
    ['deriveKey']
  );

  const key = await crypto.subtle.deriveKey(
    {
      name: 'HKDF',
      hash: 'SHA-256',
      salt: aeadSalt,
      info: aeadInfo,
    },
    sharedBaseKey,
    { name: 'AES-GCM', length: 256 },
    false,
    ['encrypt', 'decrypt']
  );

  return { key, rawKey: rawSharedSecret, transcriptBytes };
}

/**
 * Tạo nonce 12 bytes theo bộ đếm counter bằng HKDF.
 * Khớp với logic _derive_nonce() trong desktop/security/e2e.py.
 * @param {Uint8Array} rawKey
 * @param {Uint8Array} transcriptBytes
 * @param {number} counter
 * @returns {Promise<Uint8Array>}
 */
export async function deriveNonce(rawKey, transcriptBytes, counter) {
  const counterBytes = packUint64BE(counter);
  const info = concatBytes(ENC.encode('touchlink-e2e-v1|nonce|'), transcriptBytes, counterBytes);
  const salt = rawKey.slice(0, 16);

  const baseKey = await crypto.subtle.importKey(
    'raw',
    ENC.encode('nonce'),
    'HKDF',
    false,
    ['deriveBits']
  );

  const bits = await crypto.subtle.deriveBits(
    {
      name: 'HKDF',
      hash: 'SHA-256',
      salt: salt,
      info: info,
    },
    baseKey,
    96 // 12 bytes
  );

  return new Uint8Array(bits);
}

/**
 * Mã hóa dữ liệu plaintext thành gói E2E payload: counter (8B) + ciphertext (tag kèm ở cuối).
 * @param {CryptoKey} key
 * @param {Uint8Array} rawKey
 * @param {Uint8Array} transcriptBytes
 * @param {number} counter
 * @param {Uint8Array|string} plaintext
 * @returns {Promise<Uint8Array>}
 */
export async function encryptE2E(key, rawKey, transcriptBytes, counter, plaintext) {
  const data = typeof plaintext === 'string' ? ENC.encode(plaintext) : plaintext;
  const nonce = await deriveNonce(rawKey, transcriptBytes, counter);
  const aad = concatBytes(ENC.encode('touchlink-e2e-v1|aad|'), transcriptBytes);

  const cipherBuf = await crypto.subtle.encrypt(
    {
      name: 'AES-GCM',
      iv: nonce,
      additionalData: aad,
      tagLength: 128,
    },
    key,
    data
  );

  return concatBytes(packUint64BE(counter), new Uint8Array(cipherBuf));
}

/**
 * Giải mã gói E2E payload, từ chối nonce lùi hoặc lặp (chống replay attack).
 * @param {CryptoKey} key
 * @param {Uint8Array} rawKey
 * @param {Uint8Array} transcriptBytes
 * @param {number} lastRecvCounter
 * @param {Uint8Array} payloadBytes
 * @returns {Promise<{ plaintext: Uint8Array, text: string, counter: number }>}
 */
export async function decryptE2E(key, rawKey, transcriptBytes, lastRecvCounter, payloadBytes) {
  if (payloadBytes.byteLength <= 8) {
    throw new Error('E2E payload truncated');
  }
  const counter = unpackUint64BE(payloadBytes.slice(0, 8));
  if (counter <= lastRecvCounter) {
    throw new Error('E2E replay or out-of-order counter rejected');
  }

  const nonce = await deriveNonce(rawKey, transcriptBytes, counter);
  const aad = concatBytes(ENC.encode('touchlink-e2e-v1|aad|'), transcriptBytes);
  const ciphertextWithTag = payloadBytes.slice(8);

  const plainBuf = await crypto.subtle.decrypt(
    {
      name: 'AES-GCM',
      iv: nonce,
      additionalData: aad,
      tagLength: 128,
    },
    key,
    ciphertextWithTag
  );

  const plaintext = new Uint8Array(plainBuf);
  return {
    plaintext,
    text: DEC.decode(plaintext),
    counter,
  };
}

/**
 * Tính mã fingerprint ngắn (8 ký tự) để người dùng đối chiếu chéo giữa 2 máy.
 * @param {Uint8Array} rawKey
 * @returns {Promise<string>}
 */
export async function computeFingerprint(rawKey) {
  const hash = await crypto.subtle.digest('SHA-256', rawKey);
  const hex = Array.from(new Uint8Array(hash))
    .slice(0, 4)
    .map((b) => b.toString(16).padStart(2, '0'))
    .join('')
    .toUpperCase();
  return hex;
}

if (typeof window !== 'undefined') {
  window.TouchLinkCrypto = {
    setupE2EKey,
    deriveNonce,
    encryptE2E,
    decryptE2E,
    computeFingerprint,
    concatBytes,
    packUint64BE,
    unpackUint64BE,
  };
}
