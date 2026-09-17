from database.models.manager import ModelPrice
from database.operations import BaseRepository


class ModelPriceRepository(BaseRepository[ModelPrice]):
    def __init__(self, db):
        super().__init__(ModelPrice, db)
