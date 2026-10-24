from pydantic import BaseModel

class File(BaseModel):
    file_id: str
    file_name: str
    file_url: str

class FileList(BaseModel):
    file_list: list[File]