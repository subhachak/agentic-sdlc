

# Protocols a client MAY implement, and which the platform discovers by
# duck-typing rather than requiring. Declared here so adding one is a
# deliberate act recorded next to the ports, rather than a name the
# framework invariant happens to skip.
#
# A port belongs here only when an adapter that cannot do it is still a
# perfectly good adapter: an indexer pointed at one repository has no
# catalogue to list, and a deployment platform with no rollback primitive
# would have to lie or raise if the method were mandatory.
OPTIONAL_CAPABILITIES = frozenset({"RepositoryCatalogue", "RollbackCapable"})
