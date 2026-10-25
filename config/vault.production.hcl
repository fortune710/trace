# The API listener is reachable only on the private Compose secrets network.
# Unlike compose.yaml's development Vault, storage survives container restarts.
ui = false
disable_mlock = true
api_addr = "http://vault:8200"
cluster_addr = "https://vault:8201"

storage "raft" {
  path = "/vault/data"
  node_id = "trace-vault"
}

listener "tcp" {
  address = "0.0.0.0:8200"
  tls_disable = true
}
