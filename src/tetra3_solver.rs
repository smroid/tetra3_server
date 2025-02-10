// Copyright (c) 2025 Steven Rosenthal smr@dt3.org
// See LICENSE file in root directory for license terms.

use std::sync::atomic::AtomicBool;
use std::sync::{Arc, Mutex};
use std::time::Duration;

use canonical_error::{CanonicalError, failed_precondition_error};

use log::info;
use tonic::async_trait;
use tonic::transport::{Endpoint, Uri};
use tokio::net::UnixStream;
use tower::service_fn;

use cedar_elements::cedar::{ImageCoord, PlateSolution, StarInfo};
use cedar_elements::cedar_common::CelestialCoord;
use cedar_elements::solver_trait::{SolveExtension, SolveParams, SolverTrait};

use crate::tetra3_server::tetra3_client::Tetra3Client;
use crate::tetra3_subprocess::Tetra3Subprocess;

use crate::tetra3_server::{CelestialCoord as TetraCelestialCoord,
                           ImageCoord as TetraImageCoord, SolveRequest,
                           SolveResult, SolveStatus};

// Tetra3Solver is a Rust wrapper to the Cedar-solve (Python) based
// implementation of SolverTrait. Runs the Python code in a subprocess
// which processes gRPC requests from Tetra3Solver.
pub struct Tetra3Solver {
    tetra3_subprocess: Arc<Mutex<Tetra3Subprocess>>,

    // Our connection to the tetra3 gRPC server.
    client: Arc<tokio::sync::Mutex<Tetra3Client<tonic::transport::Channel>>>,
}

impl Drop for Tetra3Solver {
    fn drop(&mut self) {
        self.stop();
    }
}

impl Tetra3Solver {
    pub async fn new(tetra3_script: &str,
                     database_path: &str,
                     got_signal: Arc<AtomicBool>) -> Result<Self, CanonicalError> {
        info!("Using Tetra3 server {:?} listening at {:?}",
              tetra3_script, "/tmp/cedar.sock");
        let tetra3_subprocess = Arc::new(Mutex::new(
            Tetra3Subprocess::new(
                tetra3_script, database_path, got_signal.clone()).unwrap()));
        let client = Self::connect("/tmp/cedar.sock".to_string()).await?;

        Ok(Tetra3Solver{tetra3_subprocess,
                        client: Arc::new(tokio::sync::Mutex::new(client))})
    }

    async fn connect(tetra3_server_address: String)
        -> Result<Tetra3Client<tonic::transport::Channel>, CanonicalError>
    {
        // Set up gRPC client, connect to a UDS socket. URL is ignored.
        let mut backoff = Duration::from_millis(100);
        loop {
            let addr = tetra3_server_address.clone();
            let channel = Endpoint::try_from("http://[::]:50051").unwrap()
                .connect_with_connector(service_fn(move |_: Uri| {
                    // Connect to a Uds socket
                    UnixStream::connect(addr.clone())
                })).await;
            match channel {
                Ok(ch) => {
                    return Ok(Tetra3Client::new(ch));
                },
                Err(e) => {
                    if backoff > Duration::from_secs(20) {
                        return Err(failed_precondition_error(format!(
                            "Error connecting to Tetra server at {:?}: {:?}",
                            tetra3_server_address, e).as_str()));
                    }
                    // Give time for tetra3_server binary to start up, load its
                    // pattern database, and start to accept connections.
                    tokio::time::sleep(backoff).await;
                    backoff = backoff.mul_f32(1.5);
                }
            }
        }
    }

    async fn solve_with_client(&self, solve_request: SolveRequest)
        -> Result<SolveResult, CanonicalError> {
        match self.client.lock().await.solve_from_centroids(solve_request).await {
            Ok(response) => {
                return Ok(response.into_inner());
            },
            Err(e) => {
                return Err(failed_precondition_error(
                    format!("Error invoking plate solver: {:?}", e).as_str()));
            },
        }
    }

    pub fn stop(&mut self) {
        self.tetra3_subprocess.lock().unwrap().stop();
    }
}

#[async_trait]
impl SolverTrait for Tetra3Solver {
    async fn solve_from_centroids(&self,
                                  star_centroids: &Vec<ImageCoord>,
                                  width: usize, height: usize,
                                  extension: &SolveExtension,
                                  params: &SolveParams)
                                  -> Result<PlateSolution, CanonicalError> {
        let mut solve_request = SolveRequest::default();

        for sc in star_centroids {
            solve_request.star_centroids.push(
                TetraImageCoord{x: sc.x, y: sc.y});
        }
        solve_request.image_width = width as i32;
        solve_request.image_height = height as i32;
        if let Some((fov_est, fov_tol)) = params.fov_estimate {
            solve_request.fov_estimate = Some(fov_est);
            solve_request.fov_max_error = Some(fov_tol);
        }
        solve_request.match_radius = params.match_radius;
        solve_request.match_threshold = params.match_threshold;

        let solve_timeout: Duration = params.solve_timeout.unwrap_or(
            self.default_timeout());
        solve_request.solve_timeout =
            Some(prost_types::Duration::try_from(solve_timeout).unwrap());

        if let Some(tp_vec) = &extension.target_pixel {
            for tp in tp_vec {
                solve_request.target_pixels.push(
                    TetraImageCoord{x: tp.x, y: tp.y});
            }
        }
        if let Some(tsc_vec) = &extension.target_sky_coord {
            for tsc in tsc_vec {
                solve_request.target_sky_coords.push(
                    TetraCelestialCoord{ra: tsc.ra, dec: tsc.dec});
            }
        }
        solve_request.distortion = params.distortion;
        solve_request.return_matches = extension.return_matches;
        solve_request.return_catalog = extension.return_catalog;
        solve_request.return_rotation_matrix = extension.return_rotation_matrix;
        solve_request.match_max_error = params.match_max_error;

        let tetra_solve_result = self.solve_with_client(solve_request).await?;
        if tetra_solve_result.status != Some(SolveStatus::MatchFound.into()) {
            return Err(failed_precondition_error(format!(
                "Tetra server returned error status {:?}",
                tetra_solve_result.status).as_str()));
        }

        // Convert Tetra3 SolveResult into Cedar's PlateSolution proto.
        let mut plate_solution =
            PlateSolution{
                image_sky_coord: Some(CelestialCoord{
                    ra: tetra_solve_result.image_center_coords.as_ref().unwrap().ra,
                    dec: tetra_solve_result.image_center_coords.as_ref().unwrap().dec}),
                roll: tetra_solve_result.roll.unwrap(),
                fov: tetra_solve_result.fov.unwrap(),
                distortion: tetra_solve_result.distortion,
                rmse: tetra_solve_result.rmse.unwrap(),
                p90_error: tetra_solve_result.p90e.unwrap(),
                max_error: tetra_solve_result.maxe.unwrap(),
                num_matches: tetra_solve_result.matches.unwrap(),
                prob: tetra_solve_result.prob.unwrap(),
                epoch_equinox: tetra_solve_result.epoch_equinox.unwrap() as i32,
                epoch_proper_motion:
                tetra_solve_result.epoch_proper_motion.unwrap() as f32,
                solve_time: tetra_solve_result.solve_time.clone(),
                ..Default::default()
            };
        for tc in &tetra_solve_result.target_coords {
            plate_solution.target_sky_coord.push(
                CelestialCoord{ra: tc.ra, dec: tc.dec});
        }
        for tstic in &tetra_solve_result.target_sky_to_image_coords {
            plate_solution.target_pixel.push(
                ImageCoord{x: tstic.x, y: tstic.y});
        }
        for ms in &tetra_solve_result.matched_stars {
            plate_solution.matched_stars.push(
                StarInfo{
                    pixel: Some(ImageCoord{
                        x: ms.image_coord.as_ref().unwrap().x,
                        y: ms.image_coord.as_ref().unwrap().y}),
                    sky_coord: Some(CelestialCoord{
                        ra: ms.celestial_coord.as_ref().unwrap().ra,
                        dec: ms.celestial_coord.as_ref().unwrap().dec}),
                    mag: ms.magnitude as f32,
                });
        }
        for pc in &tetra_solve_result.pattern_centroids {
            plate_solution.pattern_centroids.push(
                ImageCoord{x: pc.x, y: pc.y});
        }
        for cs in &tetra_solve_result.catalog_stars {
            plate_solution.catalog_stars.push(
                StarInfo{
                    pixel: Some(ImageCoord{
                        x: cs.image_coord.as_ref().unwrap().x,
                        y: cs.image_coord.as_ref().unwrap().y}),
                    sky_coord: Some(CelestialCoord{
                        ra: cs.celestial_coord.as_ref().unwrap().ra,
                        dec: cs.celestial_coord.as_ref().unwrap().dec}),
                    mag: cs.magnitude as f32,
                });
        }
        if let Some(rm) = tetra_solve_result.rotation_matrix {
            plate_solution.rotation_matrix = rm.matrix_elements.clone();
        }

        Ok(plate_solution)
    }

    fn cancel(&self) {
        self.tetra3_subprocess.lock().unwrap().send_interrupt_signal();
    }

    fn default_timeout(&self) -> Duration { Duration::from_secs(5) }
}
