#!/usr/bin/perl

=head1 NAME

bt_pa_auto_switcher.py - Switch Bluetooth headset between A2DP and HSP
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

Copyright (2) 2013 Jonathan Kamens.

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

# WEBRTC VoiceEngine is Google Chat, Voice, and Talk.
my $valid_clients = qr/(?:Skype|WEBRTC VoiceEngine)/;
my $mute_corked = 1;

&main_loop;

my(%connections, %muted, $saved_volume);

sub main_loop {
    my($exp, $patidx);

    my $start_time = time();
    while (($exp && ($patidx = $exp->expect(undef, '-re', '.*\n'))) ||
	   $start_time) {
	if (! $patidx) {
	    # No successful output yet... first time through the loop, so
	    # we need to initialize, or Pulseaudio hasn't started yet.
	    if (time() - $start_time < 30) {
		$exp = Expect->spawn('pactl', 'subscribe') or die;
		$exp->log_user(0);
		$exp->log_stdout(0);
		sleep(1);
		next;
	    }
	    last;
	}
	# We've successfully read at least one event, so we're done
	# waiting for Pulseaudio to start up.
	$start_time = undef;

	$_ = $exp->match();
	next if (/on client |'change'/);
	if (/^Event 'new' on (sink-input|source-output) \#(\d+)/) {
	    my($type) = $1;
	    my($num) = $2;
	    next if (! &new($type, $num));
	    if (&both && ! &hsp) {
		&switch;
	    }
	}
	elsif (/^Event 'remove' on (sink-input|source-output) \#(\d+)/) {
	    my($type) = $1;
	    my($num) = $2;
	    next if (! &remove($type, $num));
	    if (&neither && &hsp) {
		&switch_back;
	    }
	}
    }
}

sub new {
    my($type, $num) = @_;
    my $client = &get_client($type, $num);
    return undef if (! $client);
    print "NEW: $type / $num / $client\n";
    $connections{$type}->{$num} = 1;
}

sub remove {
    my($type, $num) = @_;
    return undef if (! delete($connections{$type}->{$num}));
    print "REMOVE: $type / $num\n";
    return 1;
}

sub both {
    return undef if (scalar keys %connections != 2);

    map {
	return undef if (! %{$connections{$_}});
    } keys %connections;

    return 1;
}

sub neither {
    map {
	return undef if (%{$connections{$_}});
    } keys %connections;

    return 1;
}

sub get_client {
    local($_);
    my($type, $num) = @_;
    open(PACMD, "-|", "pacmd list-${type}s") or die;
    my($in) = 0;
    while (<PACMD>) {
	if (/^\s*index:\s+$num\b/) {
	    $in = 1;
	    next;
	}
	elsif ($in && /^\s*index:\s+\d+\b/) {
	    return undef;
	}
	elsif ($in && /^\s+application\.name = "($valid_clients)"/o) {
	    print "good client ($type, $num): $1\n";
	    return $1;
	}
	elsif ($in && /^\s+application\.name = "(.*)"/) {
	    print "bad client ($type, $num): $1\n";
	    return undef;
	}
    }
    return undef;
}

sub switch {
    my($sink_name, $card_name) = &get_running_bluez_sink();
    return if (! $sink_name);
    my $new_volume = &get_sink_volume($sink_name);
    my $source_name;
    ($source_name = $sink_name) =~ s/sink/source/;
    &mute_corked();
    print "Switching\n";
    open(PACMD, "|-", "pacmd >/dev/null") or die;
    print(PACMD "set-card-profile $card_name hsp\n");
    print(PACMD "set-default-source $source_name\n");
    print(PACMD "set-default-sink $sink_name\n");
    foreach my $sink (keys %{$connections{'sink-input'}}) {
	print(PACMD "move-sink-input $sink $sink_name\n");
    }
    foreach my $source (keys %{$connections{'source-output'}}) {
	print(PACMD "move-source-output $source $source_name\n");
    }
    if (defined($saved_volume)) {
	print "Resetting volume to $saved_volume\n";
	print(PACMD "set-sink-volume $sink_name $saved_volume\n");
    }
    close(PACMD) || warn "pacmd failed\n";
    $saved_volume = $new_volume;
}

sub switch_back {
    my($sink_name, $card_name) = &get_running_bluez_sink();
    if (! $sink_name) {
	return;
    }
    my $new_volume = &get_sink_volume($sink_name);
    print "Switching back\n";
    open(PACMD, "|-", "pacmd >/dev/null") or die;
    print(PACMD "set-card-profile $card_name a2dp\n");
    print(PACMD "set-default-sink $sink_name\n");
    if (defined($saved_volume)) {
	print "Resetting volume to $saved_volume\n";
	print(PACMD "set-sink-volume $sink_name $saved_volume");
    }
    close(PACMD) || warn "pacmd failed\n";
    $saved_volume = $new_volume;
    &unmute_corked();
}

sub get_running_bluez_sink {
    local($_);
    my($sink);
    open(STAT, "-|", "pactl stat");
    while (<STAT>) {
	if (/^Default Sink/) {
	    if (/(bluez_sink.*)/) {
		$sink = $1;
		last;
	    }
	    return undef;
	}
    }
    if ($sink) {
	my($card) = $sink;
	$card =~ s/sink/card/;
	return($sink, $card);
    }
    return ();
}

sub get_sink_volume {
    local($_);
    my($sink) = @_;
    my($sink_re) = $sink;
    $sink_re =~ s/(\W)/\\$1/g;
    my($pct, $steps);
    my $in = 0;
    open(PACMD, "-|", "pacmd list-sinks");
    while (<PACMD>) {
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
	elsif ($in && /^\s*volume steps:\s+(\d+)/) {
	    my $steps = $1;
	    my $volume = int($pct / 100 * $steps);
	    print "$sink volume: $volume / $steps\n";
	    return $volume;
	}
    }
    return undef;
}

sub get_current_profile {
    local($_);
    my($card) = @_;
    my($card_re) = $card;
    my $in = 0;
    $card_re =~ s/(\W)/\\$1/g;
    open(PACMD, "-|", "pacmd list-cards") or die;
    while (<PACMD>) {
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
    my($sink, $card) = &get_running_bluez_sink();
    my $profile = &get_current_profile($card);
    $profile eq 'hsp';
}

sub mute_corked {
    return if (! $mute_corked);

    local($_);
    local($/) = "index:";
    open(PACMD, "-|", "pacmd list-sink-inputs");
    while (<PACMD>) {
	my($app, $num);
	if (/START_CORKED/ && /muted: no/ &&
	    (($app) = /application\.name = "(.*)"/) &&
	    (($num) = /^\s*(\d+)/) && ! $connections{'sink-input'}->{$num}) {
	    $muted{$num} = $app;
	}
    }
    close(PACMD);
    return if (! %muted);
    my(%apps) = reverse %muted;
    print "Muting ", join(" ", sort keys %apps), "\n";
    open(PACMD, "|-", "pacmd >/dev/null") or die;
    foreach my $input (keys %muted) {
	print(PACMD "set-sink-input-mute $input 1\n");
	print("set-sink-input-mute $input 1\n");
    }
    close(PACMD) || warn "pacmd failed\n";
}

sub unmute_corked {
    return if (! %muted);
    print "Unmuting\n";
    open(PACMD, "|-", "pacmd >/dev/null") or die;
    foreach my $input (keys %muted) {
	print(PACMD "set-sink-input-mute $input 0\n");
    }
    close(PACMD) || warn "pacmd failed\n";
    %muted = ()
}
