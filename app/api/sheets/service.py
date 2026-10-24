from client import SheetsClient


class SheetService:
    def __init__(self,client : SheetsClient ):
        self._client = client