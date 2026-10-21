from dataclasses import dataclass


@dataclass
class InputError(Exception):
    code: str
    path: str
    detail: str

    def __str__(self) -> str:
        return f"{self.code}: {self.path}: {self.detail}"
