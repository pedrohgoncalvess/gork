from PIL import Image, ImageOps


def remove_color(image: Image.Image) -> Image.Image:
    alpha = image.getchannel("A") if "A" in image.getbands() else None
    grayscale = ImageOps.grayscale(image)

    if alpha is None:
        return grayscale.convert("RGB")

    result = grayscale.convert("RGBA")
    result.putalpha(alpha)
    return result
