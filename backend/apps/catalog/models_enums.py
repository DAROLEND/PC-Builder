from django.db import models


class CategoryKind(models.TextChoices):
    """The fixed set of slots a build can have.

    The compatibility engine keys its rules on the kind, not on the category
    name, so admins can rename categories without breaking the rules.
    """

    CPU = "cpu", "Processor"
    MOTHERBOARD = "motherboard", "Motherboard"
    RAM = "ram", "Memory"
    GPU = "gpu", "Graphics card"
    STORAGE = "storage", "Storage"
    PSU = "psu", "Power supply"
    CASE = "case", "Case"
    COOLER = "cooler", "CPU cooler"
