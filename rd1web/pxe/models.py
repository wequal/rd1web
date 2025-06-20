from django.db import models

# Create your models here.

class PxeEntry(models.Model):
    mac = models.CharField(max_length=32,unique=True)
    parameters = models.TextField()
    image= models.CharField(max_length=100)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.mac