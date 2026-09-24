"""Translate "compatible with these parts" into a database filter.

The configurator asks: "show me motherboards that fit the CPU and case I
already picked". Loading the whole catalog and running the engine on every
candidate would work, but pagination and ordering would then happen in Python.
Instead the hard, cheap rules are pushed into SQL:

* Containment (``specs__contains={"socket": "AM5"}``) compiles to
  ``specs @> '{"socket": "AM5"}'`` and is served by the GIN ``jsonb_path_ops``
  index. Note that ``specs__socket="AM5"`` would compile to
  ``specs -> 'socket' = '"AM5"'`` which the GIN index cannot use.
* Numeric limits (GPU length, cooler height) use key transforms; jsonb
  numbers compare numerically in PostgreSQL.

This is a *pre-filter*: it may let through something the engine later flags
(e.g. a low-headroom PSU warning), but it never hides a valid part for the
rules it covers. ``compatibility.check()`` stays the single source of truth.
"""

from django.db.models import Q

from apps.builds import compatibility as c


def compatible_q(kind: str, parts: list[c.Part]) -> Q:
    b = c.BuildView(parts)
    cpu, mb, case = b.one(c.CPU), b.one(c.MOTHERBOARD), b.one(c.CASE)
    psu, cooler = b.one(c.PSU), b.one(c.COOLER)
    rams, gpus = b.all(c.RAM), b.all(c.GPU)
    ram_type = rams[0].specs["memory_type"] if rams else None

    q = Q()
    if kind == c.CPU:
        if mb:
            q &= Q(specs__contains={"socket": mb.specs["socket"]})
            q &= Q(specs__contains={"supported_chipsets": [mb.specs["chipset"]]})
        if ram_type:
            q &= Q(specs__contains={"memory_types": [ram_type]})
        if cooler:
            q &= Q(specs__socket__in=cooler.specs["sockets"])

    elif kind == c.MOTHERBOARD:
        if cpu:
            q &= Q(specs__contains={"socket": cpu.specs["socket"]})
            q &= Q(specs__chipset__in=cpu.specs["supported_chipsets"])
            q &= Q(specs__memory_type__in=cpu.specs["memory_types"])
        if ram_type:
            q &= Q(specs__contains={"memory_type": ram_type})
        if case:
            q &= Q(specs__form_factor__in=case.specs["supported_form_factors"])

    elif kind == c.RAM:
        if mb:
            q &= Q(specs__contains={"memory_type": mb.specs["memory_type"]})
        elif cpu:
            q &= Q(specs__memory_type__in=cpu.specs["memory_types"])
        if ram_type:
            q &= Q(specs__contains={"memory_type": ram_type})

    elif kind == c.GPU:
        if case:
            # Unknown length stays in the list; the engine warns about it.
            q &= Q(specs__length_mm__lte=case.specs["max_gpu_length_mm"]) | ~Q(
                specs__has_key="length_mm"
            )

    elif kind == c.CASE:
        if mb:
            q &= Q(specs__contains={"supported_form_factors": [mb.specs["form_factor"]]})
        if psu:
            q &= Q(specs__contains={"psu_form_factors": [psu.specs["form_factor"]]})
        lengths = [g.specs["length_mm"] for g in gpus if "length_mm" in g.specs]
        if lengths:
            q &= Q(specs__max_gpu_length_mm__gte=max(lengths))
        if cooler and cooler.specs["type"] == "air" and "height_mm" in cooler.specs:
            q &= Q(specs__max_cooler_height_mm__gte=cooler.specs["height_mm"])
        if cooler and cooler.specs["type"] == "liquid" and "radiator_mm" in cooler.specs:
            # Cases that don't list radiator support stay; the engine warns.
            q &= Q(specs__max_radiator_mm__gte=cooler.specs["radiator_mm"]) | ~Q(
                specs__has_key="max_radiator_mm"
            )

    elif kind == c.COOLER:
        if cpu:
            q &= Q(specs__contains={"sockets": [cpu.specs["socket"]]})
        if case:
            # Unknown sizes stay in the list; the engine warns about them.
            air = Q(specs__type="air") & (
                Q(specs__height_mm__lte=case.specs["max_cooler_height_mm"])
                | ~Q(specs__has_key="height_mm")
            )
            liquid = Q(specs__type="liquid")
            if "max_radiator_mm" in case.specs:
                liquid &= Q(specs__radiator_mm__lte=case.specs["max_radiator_mm"]) | ~Q(
                    specs__has_key="radiator_mm"
                )
            q &= air | liquid

    elif kind == c.PSU:
        if case:
            q &= Q(specs__form_factor__in=case.specs["psu_form_factors"])
        others = [p for p in parts if p.kind != c.PSU]
        estimated = c.estimate_wattage(c.BuildView(others))
        if estimated:
            q &= Q(specs__wattage__gte=estimated)

    return q
