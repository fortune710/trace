path "transit/encrypt/trace-provider-credentials" {
  capabilities = ["update"]
}

path "transit/decrypt/trace-provider-credentials" {
  capabilities = ["update"]
}

path "transit/keys/trace-provider-credentials" {
  capabilities = ["read"]
}

path "transit/rewrap/trace-provider-credentials" {
  capabilities = ["update"]
}

path "transit/encrypt/trace-email-delivery" {
  capabilities = ["update"]
}

path "transit/decrypt/trace-email-delivery" {
  capabilities = ["update"]
}

path "transit/keys/trace-email-delivery" {
  capabilities = ["read"]
}
