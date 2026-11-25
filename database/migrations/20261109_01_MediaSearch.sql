-- Searchable descriptions for the shared media library.
-- depends: 20261020_02_MessageSearch
ALTER TABLE content.sup_media ADD COLUMN description TEXT;
ALTER TABLE content.sup_media ADD COLUMN description_embedding vector(2560);
