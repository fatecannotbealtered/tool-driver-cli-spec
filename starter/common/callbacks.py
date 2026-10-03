"""Replace these explicit callbacks only after defining and testing a native adapter."""


def adapter(validator, catalog):
    # Construct protocol objects only. Native work belongs in execute(validated_invocation).
    from tool_driver_sdk import StubAdapter
    return StubAdapter(validator, catalog)


def context(registry, project):
    return {"product": {"name": registry["name"], "version": registry["product_version"]},
            "profile": project["profile"], "native": {"status": "not_connected", "application_version": None,
            "reason": "No native adapter is configured. Creating this starter does not connect an application or device."},
            "limitations": ["Product capabilities remain draft; native state has not been observed."]}


def doctor(registry, project):
    result = context(registry, project)
    result.update(ready=False, checks=[{"id": "native_adapter", "status": "not_run",
                  "reason": "No native adapter is configured; no original application or device was queried."}])
    return result
