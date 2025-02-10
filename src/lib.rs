// Copyright (c) 2025 Steven Rosenthal smr@dt3.org
// See LICENSE file in root directory for license terms.

// #[allow(unused_variables)]
pub mod tetra3_solver;

// #[allow(dead_code)]
mod tetra3_subprocess;

pub mod tetra3_server {
    tonic::include_proto!("tetra3_server");
}
