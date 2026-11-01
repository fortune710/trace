import {
  buildAvatarSvg,
  loadAvatarEngine,
  svgToDataUri,
  type AvatarConfig,
} from "./avatar-config"

export const AVATAR_PNG_SIZE = 256

function loadImage(source: string): Promise<HTMLImageElement> {
  return new Promise((resolve, reject) => {
    const image = new Image()
    image.onload = () => resolve(image)
    image.onerror = () => reject(new Error("The avatar image could not be loaded."))
    image.src = source
  })
}

// Rasterises the avatar in the browser so the server only ever stores a PNG.
export async function renderAvatarPng(config: AvatarConfig): Promise<Blob> {
  const engine = await loadAvatarEngine()
  const svg = buildAvatarSvg(engine, config, { size: AVATAR_PNG_SIZE })
  const image = await loadImage(svgToDataUri(svg))
  const canvas = document.createElement("canvas")
  canvas.width = AVATAR_PNG_SIZE
  canvas.height = AVATAR_PNG_SIZE
  const context = canvas.getContext("2d")

  if (!context) {
    throw new Error("Canvas is not available.")
  }

  context.drawImage(image, 0, 0, AVATAR_PNG_SIZE, AVATAR_PNG_SIZE)

  return new Promise<Blob>((resolve, reject) => {
    canvas.toBlob((blob) => {
      if (blob) {
        resolve(blob)
      } else {
        reject(new Error("The avatar could not be converted to a PNG."))
      }
    }, "image/png")
  })
}
