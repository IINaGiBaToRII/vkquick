import asyncio
import pathlib
import time
import typing

import cv2
from mltu.configs import BaseModelConfigs
from mltu.inferenceModel import OnnxInferenceModel
from mltu.utils.text_utils import ctc_decoder, get_cer
import numpy as np
import reqsnaked
import vkquick as vq


class ImageToWordModel(OnnxInferenceModel):
    def __init__(self, char_list: typing.Union[str, list], *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.char_list = char_list

    def predict(self, image: np.ndarray):
        image = cv2.resize(image, self.input_shape[:2][::-1])

        image_pred = np.expand_dims(image, axis=0).astype(np.float32)

        preds = self.model.run(None, {self.input_name: image_pred})[0]

        text = ctc_decoder(preds, self.char_list)[0]

        return text


client = reqsnaked.Client(danger_accept_invalid_certs=True)
configs = BaseModelConfigs.load(pathlib.Path(__file__).with_name("configs.yaml"))
model = ImageToWordModel(model_path=configs.model_path, char_list=configs.vocab)


async def get_image_bytes(url, session: reqsnaked.Client):
    response = await session.send(
        reqsnaked.Request("GET", url)
    )
    content = await response.read()
    return content.as_bytes()


def solve(image_bytes: bytes):
    numpyarray = np.asarray(bytearray(image_bytes), dtype=np.uint8)
    picture = cv2.imdecode(numpyarray, cv2.IMREAD_UNCHANGED)
    return model.predict(picture)


async def captcha_handler(url: str):

    while True:
        try:
            start_time = time.time()
            image_bytes = await get_image_bytes(url, client)
            captcha_code = solve(image_bytes)
            break
        except reqsnaked.ConnectionError:
            await asyncio.sleep(2)

    to_sleep = 4 - (time.time() - start_time)
    await asyncio.sleep(to_sleep if to_sleep > 0 else 0.1)

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
