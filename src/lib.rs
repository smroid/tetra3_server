// Copyright (c) 2025 Steven Rosenthal smr@dt3.org
// See LICENSE file in root directory for license terms.

pub mod tetra3_solver;
mod tetra3_subprocess;

pub mod tetra3_server {
    tonic::include_proto!("tetra3_server");
}
