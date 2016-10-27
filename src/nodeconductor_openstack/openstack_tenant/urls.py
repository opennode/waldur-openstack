from . import views


def register_in(router):
    router.register(r'openstacktenant', views.OpenStackServiceViewSet, base_name='openstacktenant')
    router.register(r'openstacktenant-service-project-link', views.OpenStackServiceProjectLinkViewSet,
                    base_name='openstacktenant-spl')
