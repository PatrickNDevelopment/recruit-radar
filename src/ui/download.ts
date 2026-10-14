/** Hand a text file to the browser's download mechanism. Nothing leaves the machine. */
export function downloadText(
  filename: string,
  text: string,
  mime = 'text/csv;charset=utf-8',
): void {
  const blob = new Blob([text], { type: mime });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = filename;
  anchor.rel = 'noopener';
  anchor.style.display = 'none';
  document.body.append(anchor);
  anchor.click();
  anchor.remove();
  // Revoke after the browser has had time to start the download.
  setTimeout(() => URL.revokeObjectURL(url), 2000);
}
