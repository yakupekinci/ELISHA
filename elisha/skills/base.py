from abc import ABC, abstractmethod

class BaseSkill(ABC):
    name: str = "base"

    @abstractmethod
    def can_handle(self, action: str) -> bool:
        pass

    @abstractmethod
    def execute(self, action: str, params: dict) -> str:
        """return result text for LLM/TTS"""
        pass
