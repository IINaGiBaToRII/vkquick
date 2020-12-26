from __future__ import annotations

import typing as ty

from vkquick.base.serializable import UIBuilder
from vkquick.button import InitializedButton


class Element:
    def __init__(
        self,
        *,
        buttons: ty.List[InitializedButton],
        title: ty.Optional[str] = None,
        description: ty.Optional[str] = None,
        photo_id: ty.Optional[int] = None
    ):
        self.scheme = dict(buttons=[but.scheme for but in buttons])
        if title is not None:
            self.scheme.update(title=title)
        if description is not None:
            self.scheme.update(description=description)
        if photo_id is not None:
            self.scheme.update(photo_id=photo_id)

    def open_link(self, link) -> Element:
        self.scheme["action"] = {"type": "open_link", "link": link}
        return self

    def open_photo(self) -> Element:
        self.scheme["action"] = {"type": "open_photo"}
        return self


class Carousel(UIBuilder):
    def __init__(self, gen: ty.Callable[..., ty.Iterator[Element]]) -> None:
        self._gen = gen
        self.scheme = {"type": "carousel", "elements": []}

    def __call__(self, *args, **kwargs):
        self.scheme["elements"] = [
            elem.scheme for elem in self._gen(*args, **kwargs)
        ]
        return self

    @classmethod
    def build(cls, *elements: Element) -> Carousel:
        self = cls(elements.__iter__)
        return self()
