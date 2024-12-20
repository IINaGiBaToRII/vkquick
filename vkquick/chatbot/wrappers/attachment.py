from __future__ import annotations

import typing

import reqsnaked

from vkquick.base.api_serializable import APISerializableMixin
from vkquick.chatbot.base.wrapper import Wrapper
from vkquick.chatbot.utils import download_file


class Attachment(Wrapper, APISerializableMixin):
    """
    Базовый класс для всех attachment-типов
    """

    _name = None

    def represent_as_api_param(self) -> str:
        if "access_key" in self.fields:
            access_key = f"""_{self.fields["access_key"]}"""
        else:
            access_key = ""

        return "{type}{owner_id}_{attachment_id}{access_key}".format(
            type=self._name,
            owner_id=self.fields["owner_id"],
            attachment_id=self.fields["id"],
            access_key=access_key,
        )


class AudioMessage(Attachment):
    _name = "audiomsg"

    async def download(
        self, *, session: typing.Optional[reqsnaked.Client] = None
    ) -> bytes:
        return await download_file(
            self.fields["link_ogg"], session=session
        )


class Audio(Attachment):
    _name = "audio"

    async def download(
        self, *, session: typing.Optional[reqsnaked.Client] = None
    ) -> bytes:
        return await download_file(
            self.fields["url"], session=session
        )


class Video(Attachment):
    _name = "video"

    async def download_lowest_quality(
        self, *, session: typing.Optional[reqsnaked.Client] = None
    ) -> bytes:
        url = list(self.fields["files"].items())[0]
        return await download_file(
            url[1], session=session
        )

    async def download_with_quality(
        self,
        quality: str,
        *,
        session: typing.Optional[reqsnaked.Client] = None,
    ) -> bytes:
        for video_quality, url in self.fields["files"].items():
            if video_quality == quality:
                return await download_file(url, session=session)
            raise ValueError(f"There isn’t a quality `{quality}` in available qualities")

    async def download_highest_quality(
        self, *, session: typing.Optional[reqsnaked.Client] = None
    ) -> bytes:
        highest_quality_url = ""
        for video_quality, url in self.fields["files"].items():
            if "mp4" in video_quality:
                highest_quality_url = url
            elif highest_quality_url:
                return await download_file(
                    highest_quality_url, session=session
                )


class Photo(Attachment):
    _name = "photo"

    async def download_min_size(
        self, *, session: typing.Optional[reqsnaked.Client] = None
    ) -> bytes:
        return await download_file(
            self.fields["sizes"][0]["url"], session=session
        )

    async def download_with_size(
        self,
        size: str,
        *,
        session: typing.Optional[reqsnaked.Client] = None,
    ) -> bytes:
        for photo_size in self.fields["sizes"]:
            if photo_size["type"] == size:
                return await download_file(photo_size["url"], session=session)
        raise ValueError(f"There isn’t a size `{size}` in available sizes")

    async def download_max_size(
        self, *, session: typing.Optional[reqsnaked.Client] = None
    ) -> bytes:
        return await download_file(
            self.fields["sizes"][-1]["url"], session=session
        )


class Document(Attachment):
    _name = "doc"

    async def download(
        self, *, session: typing.Optional[reqsnaked.Client] = None
    ) -> bytes:
        return await download_file(
            self.fields["url"], session=session
        )


class VideoMessage(Attachment):
    _name = "video_message"

