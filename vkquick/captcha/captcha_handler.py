import asyncio
import pathlib
import time
import uuid


import aiofiles
import reqsnaked
import numpy
import onnxruntime
import PIL.Image


import vkquick as vq


base_path = pathlib.Path(__file__)

captcha_session = onnxruntime.InferenceSession(str(base_path.with_name("captcha_model.onnx")))
ctc_session = onnxruntime.InferenceSession(str(base_path.with_name("ctc_model.onnx")))

codemap = " 24578acdehkmnpqsuvxyz"


def generate_string(suffix: str = ""):
    return f"{uuid.uuid4().hex}{suffix}"


def generate_file(extension: str, base: pathlib.Path = base_path) -> pathlib.Path:
    file_directory = base.with_name(generate_string(suffix=f".{extension}"))
    return file_directory


async def read_bytes_from_url(
        url: str,
        max_size: float = 209715200,
        client: reqsnaked.Client = None
) -> bytes:
    client = client or reqsnaked.Client()
    response = await client.send(reqsnaked.Request("GET", url))
    if float(response.headers.to_dict().get("content-length", -1)) < max_size:  # type: ignore
        return (await response.read()).as_bytes()


async def save_bytes(bytes_: bytes, extension: str) -> pathlib.Path:
    directory = generate_file(extension)
    async with aiofiles.open(directory, "wb") as f:
        await f.write(bytes_)
    return directory


async def download_image(url: str) -> pathlib.Path:
    image_bytes = await read_bytes_from_url(url)
    return await save_bytes(image_bytes, "png")


async def asolve(url: str):
    file = await download_image(url)
    img = PIL.Image.open(file).resize((128, 64)).convert("RGB")

    x = numpy.array(img).reshape(1, -1)
    x = numpy.expand_dims(x, axis=0)
    x = x / numpy.float32(255.0)

    out = captcha_session.run(
        None, dict([(inp.name, x[n]) for n, inp in enumerate(captcha_session.get_inputs())])
    )
    out = ctc_session.run(
        None,
        dict(
            [(inp.name, numpy.float32(out[n])) for n, inp in enumerate(ctc_session.get_inputs())]
        ),
    )
    file.unlink()
    return "".join([codemap[c] for c in numpy.uint8(out[-1][out[0] > 0])])  # type: ignore


captcha = {"count": 0}


async def captcha_handler(url):
    start_time = time.time()
    captcha_code = await asolve(url)
    to_sleep = 1.5 - (time.time() - start_time)
    await asyncio.sleep(to_sleep if to_sleep > 0 else 0.1)
    captcha["count"] += 1
    return captcha_code


async def wrap_captcha(cb):

    captcha_sid = None
    captcha_key = None
    while True:
        try:
            return await cb({"captcha_sid": captcha_sid, "captcha_key": captcha_key})
        except vq.APIError[vq.CODE_14_CAPTCHA] as err:
            captcha_sid = err.extra_fields["captcha_sid"]
            captcha_key = await captcha_handler(err.extra_fields["captcha_img"])
