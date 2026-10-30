from django.db import transaction
from django.db.models.signals import post_save
from django.dispatch import receiver

from apps.properties.models import PropertyPolicy


@receiver(post_save, sender=PropertyPolicy)
def reindex_on_save(sender, instance, **kwargs):
    from .tasks import reindex_policy

    transaction.on_commit(lambda: reindex_policy.delay(instance.pk))
