/** Preserve the whole chosen picture, with a bounded account-profile payload. */
export async function accountAvatarImage(file: File): Promise<string> {
  if (!file.size || file.size > 2 * 1024 * 1024 || !["image/png", "image/jpeg", "image/webp"].includes(file.type)) throw new Error("请选择不超过 2MB 的 PNG、JPG 或 WebP 图片。");
  const url = URL.createObjectURL(file), image = new Image();
  try {
    await new Promise<void>((resolve, reject) => { image.onload = () => resolve(); image.onerror = () => reject(new Error("图片无法读取，请换一张图片。")); image.src = url; });
    if (!image.naturalWidth || !image.naturalHeight || image.naturalWidth > 16384 || image.naturalHeight > 16384) throw new Error("图片尺寸过大或无效。");
    const scale = Math.min(1, 384 / Math.max(image.naturalWidth, image.naturalHeight));
    const canvas = document.createElement("canvas"); canvas.width = Math.max(1, Math.round(image.naturalWidth * scale)); canvas.height = Math.max(1, Math.round(image.naturalHeight * scale));
    const context = canvas.getContext("2d"); if (!context) throw new Error("当前设备无法处理头像图片。");
    context.drawImage(image, 0, 0, canvas.width, canvas.height);
    const png = canvas.toDataURL("image/png"); if (png.length <= 196608) return png;
    // JPEG has no alpha; use an explicit white background when PNG is too large.
    context.globalCompositeOperation = "destination-over"; context.fillStyle = "#fff"; context.fillRect(0, 0, canvas.width, canvas.height);
    for (const quality of [0.85, 0.65, 0.45]) { const result = canvas.toDataURL("image/jpeg", quality); if (result.length <= 196608) return result; }
    throw new Error("头像图片处理后仍然过大，请换一张图片。");
  } finally { URL.revokeObjectURL(url); }
}
