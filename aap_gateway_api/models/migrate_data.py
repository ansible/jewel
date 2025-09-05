import time

from django.db import models


class MigrateServiceDataHasRan(models.Model):
    """
    Model to track whether the migrate_service_data command has been successfully executed.

    This model is used to enforce that service authentication is blocked until the migration
    has been completed. Only one instance of this model should exist.
    """

    has_ran = models.BooleanField(default=False, help_text="True if migrate_service_data has completed successfully, False otherwise")

    class Meta:
        verbose_name = "Migrate Service Data Flag"
        verbose_name_plural = "Migrate Service Data Flags"

    def __str__(self):
        return f"Migration completed: {self.has_ran}"

    @classmethod
    def get_instance(cls):
        """
        Get or create the single instance of this flag.

        Returns:
            MigrateServiceDataHasRan: The singleton instance
        """
        instance, _ = cls.objects.get_or_create(defaults={'has_ran': False})
        return instance

    @classmethod
    def has_migration_completed(cls):
        """
        Check if the migration has been completed.

        Caches the value for 5 seconds to avoid hitting the database on every request.

        Returns:
            bool: True if migration has completed, False otherwise
        """
        now = time.monotonic()
        f = cls.has_migration_completed.__func__
        if hasattr(f, "_ts") and (now - f._ts) < 5 and hasattr(f, "_val"):
            return f._val

        has_ran = cls.get_instance().has_ran
        f._ts = now
        f._val = has_ran
        return has_ran

    @classmethod
    def mark_migration_completed(cls):
        """
        Mark the migration as completed.
        """
        instance = cls.get_instance()
        instance.has_ran = True
        instance.save()

    @classmethod
    def mark_migration_not_completed(cls):
        """
        Mark the migration as not completed.

        This is not used currently, but offered here for completeness and
        for development purposes.
        If we ever need to set this to False in a migration file, we likely
        will need to implement a custom object manager to do this.
        """
        instance = cls.get_instance()
        instance.has_ran = False
        instance.save()

    def save(self, *args, **kwargs):
        # Ensure only one instance exists
        self.pk = 1
        super().save(*args, **kwargs)

        # Clear the cache
        f = self.__class__.has_migration_completed.__func__
        if hasattr(f, "_val"):
            del f._val
