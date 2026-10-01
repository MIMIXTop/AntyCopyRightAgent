from pydantic import BaseModel

class LinkMaterial(BaseModel):
    url: str
    title: str | None = None

    def to_classroom_payload(self) -> dict:
        payload = {"url": self.url}
        if self.title:
            payload["title"] = self.title
        return {"link": payload}

class DriveFileMaterial(BaseModel):
    file_id: str
    title: str | None = None
    share_mode: str = "VIEW"

    def to_classroom_payload(self) -> dict:
        file_data = {"id": self.file_id}
        if self.title:
            file_data["title"] = self.title
        return {
            "driveFile": {
                "driveFile": file_data,
                "shareMode": self.share_mode
            }
        }