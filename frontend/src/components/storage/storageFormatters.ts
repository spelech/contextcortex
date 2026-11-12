export function formatStorageBytes(bytes: number): string {
  if (!bytes || bytes === 0) return '0 B';
  const k = 1024;
  const sizes = ['B', 'KB', 'MB', 'GB'];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i];
}

export function formatStorageDate(timestamp: number): string {
  if (!timestamp) return '-';
  const timeMs = timestamp < 1e11 ? timestamp * 1000 : timestamp;
  return new Date(timeMs).toLocaleString();
}
