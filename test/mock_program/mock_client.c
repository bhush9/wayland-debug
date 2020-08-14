#include <wayland-client.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "mock_program.h"

static struct wl_display* display;
static struct wl_registry* registry;
static struct wl_compositor* compositor;

static void registry_global(
    void* data,
    struct wl_registry* registry,
    uint32_t id,
    const char* name,
    uint32_t version)
{
    (void)data;
    if (strcmp(wl_compositor_interface.name, name) == 0)
    {
        compositor = wl_registry_bind(registry, id, &wl_compositor_interface, version);
    }
}

static void registry_global_remove(void* data, struct wl_registry* registry, uint32_t id)
{
    (void)data; (void)registry;
    printf("fatal: registry.global_remove() not implemented (id: %d)", id);
    exit(1);
}

static const struct wl_registry_listener registry_listener = {
    .global = registry_global,
    .global_remove = registry_global_remove,
};

static void _dispatch()
{
    while (wl_display_prepare_read(display) != 0)
    {
        wl_display_dispatch_pending(display);
    }

    wl_display_flush(display);
}

void mock_client_init()
{
    display = wl_display_connect(socket_name());
    if (!display)
    {
        printf("wayland_proxy_create(): can't connect to host Wayland display %s\n", socket_name());
        exit(1);
    }

    registry = wl_display_get_registry(display);
    wl_registry_add_listener(registry, &registry_listener, NULL);

    _dispatch();
}

int mock_client_get_display_fd()
{
    return wl_display_get_fd(display);
}

void mock_client_dispatch()
{
    wl_display_read_events(display);
    _dispatch();
}

void mock_client_deinit()
{
    wl_display_disconnect(display);
}