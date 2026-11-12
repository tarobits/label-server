// Decode both views before replacing the editor's last complete raster. Geometry
// and artwork then update together, while pointer feedback stays synchronous.
export async function decodeLabel(preview: { png: string; design_png: string }) {
  await Promise.all(
    [...new Set([preview.png, preview.design_png])].map(async (source) => {
      const image = new Image()
      image.src = source
      await image.decode()
    }),
  )
}
