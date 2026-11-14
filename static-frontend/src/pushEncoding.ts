export function base64url(buffer: ArrayBuffer) {
  return btoa(String.fromCharCode(...new Uint8Array(buffer))).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
}
export function decodeKey(key: string) {
  const value = key.replace(/-/g, '+').replace(/_/g, '/');
  return Uint8Array.from(atob(value + '='.repeat((4 - value.length % 4) % 4)), character => character.charCodeAt(0));
}
