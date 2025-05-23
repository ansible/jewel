def get_model_lookup_keys(ModelCls):
    """
    Determine the field names that can be used to uniquely look up existing instances of the given model class
    This method returns a set of the unique fields (not including the pk) and fields that are flattened from the unique_together tuples
    Note that we're excluding the pk in this use case because the pk is assigned by the database, which may differ across services
    """

    lookup_fields = set()

    # First the concrete and unique fields
    for field in ModelCls._meta.fields:
        if field.unique and field != ModelCls._meta.pk:
            lookup_fields.add(field.name)

    # Now, the flattened unique_together fields
    for unique_together in ModelCls._meta.unique_together:
        for field in unique_together:
            if field != ModelCls._meta.pk:
                lookup_fields.add(field)

    return lookup_fields
