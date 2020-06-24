#!/usr/bin/perl

=head1 NAME

bt_pa_auto_switcher.pl - Switch Bluetooth headset between A2DP and HSP
automatically with Pulseaudio

=head1 DESCRIPTION

Bluetooth headsets generally support two profiles: High Fidelity
Playback, a.k.a., A2DP, and Telephony Duplex, a.k.a., HSP/HFP or just
HSP. A2DP is for stereo audio output with the microphone disabled; HSP
is for mono output and mono microphone input.

Cell phones seem to be smart enough to know how to do the right thing
automatically, switching back and forth between the A2DP and HSP
profile automatically depending on whether the Microphone is in use,
but Pulseaudio and Bluez, the most common audio and Bluetooth
frameworks for Linux, don't know how to do this.

This script "eavesdrops" on Pulseaudio events and automatically
switches from A2DP to HSP if an application tries to use both output
and input at the same time, then it switches back when everyone is
finished using the microphone.

Furthermore, the script automatically mutes other sound sources while
the microphone is in use and unmutes them afterward.

Finally, it also tries to remember the volume that was set on the
headset for A2DP and HSP/HFP, and restore it when switching between
them, because Pulseaudio doesn't seem to do this automatically and
it's really annoying when it switches to full volume HSP/HFP and your
ears get blasted.

=head1 CONFIGURATION

You need the L<"Expect" perl
module|http://search.cpan.org/~rgiersig/Expect-1.21/> installed for
this script to work.

Set C<$mute_corked> to 0 below if you don't want other applications
muted while you're using the microphone. However, see the caveat
below.

Edit the C<$valid_clients> variable below to match the names of
clients for which you want the profile switching to be done. This is
necessary because there are all kinds of "fake" connection events,
e.g., from the sound settings applet. You can find out the correct
client name to use by running C<pacmd list-sink-inputs> while the
client is using the microphone and locating its "application.name"
property.  Feel free to email me additions to the list of clients;
I've initially populated it with the apps that I use frequently.

Once the script is configured properly, either start it up manually or
configure something to run it automatically when you log in, e.g., by
adding it as a startup program in gnome-session-properties. When the
script starts up it will wait for up to 30 seconds for Pulseaudio to
start, in case it gets started on login before Pulseaudio is started.

=head1 CAVEATS / TODO

The script in its current form works only with Pulseaudio and
Bluez. It could probably be made more generalized, and I'd happy take
patches to do that.

I'd happily take a patch to replace the usage of the non-standard
Expect module with code that uses only standard Perl modules.

The "module-role-cork" plugin does not seem to play nicely with this
script, so if you want to use this script, you need to disable that
plugin, e.g., by commenting it out in F</etc/pulse/default.pa> and
restarting pulseaudio, even if you set C<$mute_corked> to 0. I'd
gladly accept patches to make the script work better with the plugin.

I probably should have written this as a Pulseaudio plugin. However, I
wanted to solve the problem fast, and for me, personally, a Perl
script was the fastest solution.

=head1 THEORY OF OPERATION

The script uses "C<pactl subscribe>" to subscribe to Pulseaudio events
and watch for the birth and death of "sink-input" and "source-output"
connections to Pulseaudio. It filters these events using
C<$valid_clients> to only pay attention to clients that are known to
actually use the microphone.

When the script notices that there is at least one active sink-input
and source-output that made it through the filter, it finds the active
Bluetooth audio device and switches it to the HSP profile. Before
doing the switch, it saves the current audio volume and then mutes
other clients generating output, unless C<$mute_corked> is set to 0.

After doing the switch, it checks to see if it has a saved volume
level from the last time the HSP profile was used, and if so, restores
the volume setting to that level.

When all of the 2-way audio clients have stopped using audio, the
script works in reverse to switch back to A2DP: it saves the volume
for next time, switches back to the A2DP profile, restores the
previous A2DP volume, and unmutes the muted audio output clients.

=head1 SEE ALSO

You may also find useful my
L<script|http://blog.kamens.us/2012/10/05/pulseaudio-switch-to-headset-automatically-when-its-plugged-in-docked/>
to switch to a Bluetooth or USB headset automatically when it's
plugged in or paired.

=head1 PEEVES

Like many other things in Pulseaudio, the "division of labor" between
C<pactl> and C<pacmd> is entirely incomprehensible and seemingly
unnecessary. It's impossible to understand why there isn't one tool
that does everything both of these existing tools do, rather than
functionality being split seemingly arbitrarily between the two tools.

=head1 REPOSITORY

http://github.com/jikamens/bt_pa_auto_switcher

=head1 AUTHOR

Jonathan Kamens E<lt>jik@kamens.usE<gt>

=head1 COPYRIGHT

Copyright (c) 2013,2017,2020 Jonathan Kamens.

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or (at
your option) any later version.

This program is distributed in the hope that it will be useful, but
WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program.  If not, see L<http://www.gnu.org/licenses/>.

=cut

use strict;
use warnings;

use Expect;
use File::Basename;

# https://github.com/jikamens/bt_pa_auto_switcher/issues/1
#
# Make sure output of pulseaudio commands is English even on systems
# where that is not the dominant language, so that we can parse it as
# expected.
$ENV{"LC_ALL"} = "C";

# WEBRTC VoiceEngine is Google Chat, Voice, and Talk.
# Zoom is a bit problematic. Theoretically, it *should* only use the speaker
# and microphone while it's in a meeting. Unfortunately, sometimes it stays
# connected to the speaker even when it's not in a meeting, which means we have
# to treat it as a persistent speaker user. Worse, sometimes it stays connected
# to *both* the speaker and the microphone even when it isn't in a meeting.
# When that happens this script can't do the right thing, because it can't
# detect that Zoom isn't done if Zoom doesn't release the microphone. If you
# notice that your headset is still in HSP mode after you're done with a Zoom
# call, you need to exit the Zoom client entirely, which will cause it to
# release the microphone connection, at which point this script will do the
# right thing.
my $valid_clients = qr/^(?:Skype|ZOOM VoiceEngine|WEBRTC VoiceEngine|Google Chrome(?: input)?)$/;
# Clients that sometimes use both the speaker and microphone and other times
# use just the speaker need to be matched by this regexp.
my $persistent_speaker_users = qr/^(?:Google Chrome|ZOOM VoiceEngine)$/;
# If a client uses a different name for connecting to the microphone than
# it uses for connecting to the speaker, that needs to be mapped here.
my %client_name_map = (
    'Google Chrome input' => 'Google Chrome'
    );
my $mute_corked = 1;
my $whoami = basename $0;
my $verbose = 0;

my(%connections, %muted, $saved_volume);
my $alarmed = 1;

&main_loop;

sub main_loop {
    my($exp, $patidx);

    $SIG{'ALRM'} = \&check;

    eval { # So the script doesn't die if Pulseaudio isn't running yet
        &populate_initial_clients;
    };
    
    my $start_time = time();
    while ($alarmed) {
        $alarmed = undef;
        while (($exp && ($patidx = $exp->expect(undef, "-re", ".*\\n"))) ||
               $start_time) {
            if (! $patidx) {
                # No successful output yet... first time through the loop, so
                # we need to initialize, or Pulseaudio hasn't started yet.
                if (time() - $start_time < 30) {
                    print("Spawning pactl subscribe\n");
                    $exp = Expect->spawn("pactl", "subscribe") or die;
                    $exp->log_user(0);
                    $exp->log_stdout(0);
                    sleep(1);
                    next;
                }
                last;
            }
            # We've successfully read at least one event, so we're done
            # waiting for Pulseaudio to start up.
            if ($start_time) {
                # In case the one above failed because Pulseaudio wasn't
                # running yet.
                &populate_initial_clients;
                $start_time = undef;
            }

            $_ = $exp->match();
            next if (/on client |'change'/);
            if (/^Event 'new' on (sink-input|source-output) \#(\d+)/) {
                my($type) = $1;
                my($num) = $2;
                next if (! &new($type, $num));
                alarm(1);
            }
            elsif (/^Event 'remove' on (sink-input|source-output) \#(\d+)/) {
                my($type) = $1;
                my($num) = $2;
                next if (! &remove($type, $num));
                alarm(1);
            }
        }
    }
}

sub populate_initial_clients {
    foreach my $type ('sink-input', 'source-output') {
        my(@clients) = &get_client($type);
        return if (! @clients);
        foreach my $client (@clients) {
            next if (! &new($type, @{$client}));
            alarm(1);
        }
    }
}

sub check {
    $alarmed = 1;
    print("Quiet for one second, so checking for state change\n");
    if (&both && ! &hsp) {
        &switch;
    }
    elsif (&time_to_go) {
        &switch_back;
    }
    print("Done checking for state change\n");
}

sub new {
    my($type, $num, $client) = @_;
    if (! $client) {
        ($client) = &get_client($type, $num);
        return undef if (! $client);
        $client = $client->[1];
    }
    $client = $client_name_map{$client} || $client;
    print "$whoami: NEW: $type / $num / $client\n";
    $connections{$type}->{$num} = $client;
}

sub remove {
    my($type, $num) = @_;
    my $name;
    return undef if (! ($name = delete($connections{$type}->{$num})));
    print "$whoami: REMOVE: $type / $num / $name\n";
    return 1;
}

sub both {
    return undef if (scalar keys %connections != 2);

    map {
	return undef if (! %{$connections{$_}});
    } keys %connections;

    return 1;
}

sub time_to_go {
    # It's time to switch back when all persistent clients are no longer using
    # the microphone and all non-persistent client are no longer using either
    # the microphone or the speaker.
    return undef if (! &hsp); # Don't need to go if we're already gone
    my(%types, %counts);
    foreach my $type (keys %connections) {
        while (my($num, $name) = each %{$connections{$type}}) {
            $types{$name}->{$type} = 1;
        }
    }
    foreach my $name (keys %types) {
        $counts{$name} = scalar %{$types{$name}};
    }
    while (my($name, $count) = each %counts) {
        if ($name =~ /$persistent_speaker_users/o and $counts{$name} == 2) {
            return undef;
        }
        if ($name !~ /$persistent_speaker_users/o and $counts{$name}) {
            return undef;
        }
    }
    return 1;
}

sub pacmd {
    my($cmd) = @_;
    my $output = `pacmd $cmd`;
    if ($?) {
        warn("pacmd $cmd exited non-zero\n");
        return undef;
    }
    chomp($output);
    my $multiline = ($output =~ /\n/);
    if ($output and ($verbose or !$multiline)) {
        print("pacmd $cmd output: $output\n");
    }
    else {
        print("pacmd $cmd\n");
    }
    return $output;
}

sub get_client {
    local($_);
    my($type, $want_num) = @_;
    my $cmd = "list-${type}s";
    my(@clients, $output);
    for (my $tries = 0; $tries < 5; $tries++) {
        $output = &pacmd($cmd);
        next if (! defined($output));
        for (split(/index:\s*/, $output)) {
            my($num) = /^(\d+)/;
            next if (!$num or ($want_num and $want_num != $num));
            next if (! /^\s+application\.name = "(.*)"/mo);
            my $name = $1;
            if ($name =~ /$valid_clients/o) {
                print "$whoami: good client ($type, $num): $name\n";
                push(@clients, [$num, $name]);
                next;
            }
            if ($want_num) {
                print "$whoami: bad client ($type, $num): $name\n";
                return @clients;
            }
        }
        if (@clients) {
            return @clients;
        }
        last if (! $want_num);
        sleep(1);
    }
    if ($output !~ /available\.$/m) {
        die("pacmd $cmd looking for index #$want_num failed, aborting. ",
            "Output:\n", $output);
    }
    return @clients;
}

sub switch {
    my($device, $mode) = &get_running_bluez_device();
    return if (! $device);
    my $card = &device_card($device);
    my $current_source = &device_source($device, $mode);
    my $new_source = &device_source($device, "headset_head_unit");
    my $current_sink = &device_sink($device, $mode);
    my $new_sink = &device_sink($device, "headset_head_unit");
    my $new_volume = ($current_sink ne $new_sink) ?
        &get_sink_volume($current_sink) : undef;
    &mute_corked();
    print "$whoami: Switching\n";
    &pacmd("set-card-profile $card headset_head_unit");
    &pacmd("set-default-source $new_source");
    &pacmd("set-default-sink $new_sink");
    foreach my $sink_input (keys %{$connections{"sink-input"}}) {
	&pacmd("move-sink-input $sink_input $new_sink");
    }
    foreach my $source_output (keys %{$connections{"source-output"}}) {
	&pacmd("move-source-output $source_output $new_source");
    }
    if (defined($saved_volume)) {
	print "Resetting volume to $saved_volume\n";
	&pacmd("set-sink-volume $new_sink $saved_volume");
    }
    $saved_volume = $new_volume;
}

sub switch_back {
    my($device, $mode) = &get_running_bluez_device();
    return if (! $device);
    my $card = &device_card($device);
    my $current_sink = &device_sink($device, $mode);
    my $new_sink = &device_sink($device, "a2dp_sink");
    my $new_volume = ($current_sink ne $new_sink) ?
        &get_sink_volume($current_sink) : undef;
    print "$whoami: Switching back\n";
    &pacmd("set-card-profile $card a2dp_sink");
    &pacmd("set-default-sink $new_sink");
    if (defined($saved_volume)) {
	print "$whoami: Resetting volume to $saved_volume\n";
	&pacmd("set-sink-volume $new_sink $saved_volume");
    }
    $saved_volume = $new_volume;
    &unmute_corked();
}

sub device_card {
    my($device) = @_;
    return "bluez_card.$device";
}

sub device_source {
    my($device, $type) = @_;
    return "bluez_source.$device.$type";
}

sub device_sink {
    my($device, $type) = @_;
    return "bluez_sink.$device.$type";
}

sub get_running_bluez_device {
    local($_);
    my($sink);
    open(STAT, "-|", "pactl info");
    while (<STAT>) {
	if (/^Default Sink/) {
	    if (/bluez_sink\.([^.]+)\.(.*)/) {
                return($1, $2);
	    }
	    return undef;
	}
    }
    return undef;
}

sub get_sink_volume {
    local($_);
    my($sink) = @_;
    my($sink_re) = $sink;
    $sink_re =~ s/(\W)/\\$1/g;
    my($pct, $steps);
    my $output = &pacmd("list-sinks");
    die if (! defined($output));
    my $in = 0;
    for (split(/\n/, $output)) {
	if (/^\s*name: <$sink_re>/) {
	    $in = 1;
	    next;
	}
	elsif ($in && m/^\s*name:/) {
	    return undef;
	}
	elsif ($in && /^\s*volume:.*?\b(\d+)%/) {
	    $pct = $1;
	    next;
	}
	elsif ($in && /^\s*base volume:\s+(\d+)/) {
	    my $base = $1;
	    my $volume = int($pct / 100 * $base);
	    print "$whoami: $sink volume: $volume / $base\n";
	    return $volume;
	}
    }
    return undef;
}

sub get_current_profile {
    local($_);
    my($device) = @_;
    return undef if (! $device);
    my($card_re) = &device_card($device);
    $card_re =~ s/(\W)/\\$1/g;
    my $output = &pacmd("list-cards");
    die if (! defined($output));
    my $in = 0;
    for (split(/\n/, $output)) {
	if (/^\s*name: <$card_re>/) {
	    $in = 1;
	    next;
	}
	elsif ($in && m/^\s*name:/) {
	    return undef;
	}
	elsif ($in && /^\s*active profile: <(.*)>/) {
	    return $1;
	}
    }
    return undef;
}

sub hsp {
    my($device, $mode) = &get_running_bluez_device();
    my $profile = &get_current_profile($device);
    $profile and $profile eq "headset_head_unit";
}

sub mute_corked {
    return if (! $mute_corked);

    local($_);
    my $output = &pacmd("list-sink-inputs");
    for (split(/index:/, $output)) {
	my($app, $num);
	if (/START_CORKED/ && /muted: no/ &&
	    (($app) = /application\.name = "(.*)"/) &&
	    (($num) = /^\s*(\d+)/) && ! $connections{"sink-input"}->{$num}) {
	    $muted{$num} = $app;
	}
    }
    return if (! %muted);
    my(%apps) = reverse %muted;
    print "$whoami: Muting ", join(" ", sort keys %apps), "\n";
    foreach my $input (keys %muted) {
	&pacmd("set-sink-input-mute $input 1");
    }
}

sub unmute_corked {
    return if (! %muted);
    print "$whoami: Unmuting\n";
    foreach my $input (keys %muted) {
	&pacmd("set-sink-input-mute $input 0");
    }
    %muted = ()
}
