type PreviewImage = { src: string; decode(): Promise<void> };

type PreviewEnvironment = {
  createObjectURL(blob: Blob): string;
  revokeObjectURL(url: string): void;
  createImage(): PreviewImage;
};

// A fetched blob is not necessarily a displayable image. Decode before exposing
// the URL, and keep ownership explicit through cancellation and failed retries.
export async function loadPhotoPreview(
  fetchBlob: () => Promise<Blob>,
  signal: AbortSignal,
  environment: PreviewEnvironment = {
    createObjectURL: (blob) => URL.createObjectURL(blob),
    revokeObjectURL: (url) => URL.revokeObjectURL(url),
    createImage: () => new Image(),
  },
): Promise<{ url: string; dispose(): void }> {
  signal.throwIfAborted();
  const blob = await fetchBlob();
  signal.throwIfAborted();
  const url = environment.createObjectURL(blob);
  let disposed = false;
  const dispose = () => {
    if (disposed) return;
    disposed = true;
    environment.revokeObjectURL(url);
  };
  signal.addEventListener("abort", dispose, { once: true });
  try {
    const image = environment.createImage();
    image.src = url;
    await image.decode();
    signal.throwIfAborted();
    return { url, dispose };
  } catch (failure) {
    dispose();
    throw failure;
  } finally {
    signal.removeEventListener("abort", dispose);
  }
}
