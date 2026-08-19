from . import models



def folder_form(*args, **kwargs):
    form = models.Folder
    Fields = [
        'name',
        'parent'
    ]

